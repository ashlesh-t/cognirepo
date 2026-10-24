# SPDX-FileCopyrightText: 2026 Ashlesh T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""``cognirepod``: the supervisor. ``python -m interface.daemon.supervisor`` (started by the first client that needs it).

It does not sit in the data path. A client asks ``worker.ensure {repo}`` and gets the repo worker's socket; the
supervisor starts that worker (detached) if it is not running, keeps at most ``daemon.max_workers`` of them, and exits
after ``daemon.idle_exit_secs`` with no workers. Liveness is an exclusive lock on ``daemon.lock`` held for the life of
the process, so a stale pid file can never be mistaken for a running daemon.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import subprocess  # nosec B404 — fixed argv only
import sys
import threading
import time
from typing import Any

from core.config import procutil
from core.config.atomic import atomic_json_dump
from interface.daemon import paths, protocol
from interface.daemon.rpc_server import Connection, RpcServer

logger = logging.getLogger("cognirepo.daemon.supervisor")


def _worker_call(sock_path: str, method: str, params: dict[str, Any] | None = None, timeout: float = 3.0) -> Any:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(sock_path)
        return protocol.call(s, method, params)
    finally:
        s.close()


class WorkerHandle:
    def __init__(self, repo: str, sock: str, proc: subprocess.Popen, log: str) -> None:
        self.repo, self.sock, self.proc, self.log = repo, sock, proc, log
        self.started = time.time()
        self.last_used = time.time()

    def alive(self) -> bool:
        return self.proc.poll() is None


class Supervisor:
    def __init__(self) -> None:
        from core.config.version import __version__  # pylint: disable=import-outside-toplevel
        self.version = __version__
        self.started = time.time()
        self.last_busy = time.time()
        self.workers: dict[str, WorkerHandle] = {}
        self._lock = threading.RLock()
        self._repo_locks: dict[str, threading.Lock] = {}
        self.server = RpcServer(paths.supervisor_socket(), {
            "hello": self.h_hello, "ping": lambda c, p: "pong", "worker.ensure": self.h_ensure,
            "worker.stop": self.h_worker_stop, "status": self.h_status, "shutdown": self.h_shutdown,
        }, name="supervisor")

    # -- handlers -------------------------------------------------------------------------------
    def h_hello(self, _conn: Connection, _params):
        return {"version": self.version, "pid": os.getpid(), "started": self.started, "workers": len(self.workers)}

    def h_ensure(self, _conn: Connection, params):
        repo = self._validated_repo(params.get("repo"))
        self.last_busy = time.time()
        with self._lock:
            lock = self._repo_locks.setdefault(repo, threading.Lock())
        with lock:                                     # two clients asking for the same repo spawn ONE worker
            with self._lock:
                handle = self.workers.get(repo)
                if handle is not None and not handle.alive():
                    self.workers.pop(repo, None)
                    handle = None
            if handle is not None and not self._responsive(handle):
                # A process that is not exited but does not answer (wedged, or a just-killed one not yet reaped) must
                # never be handed to a client: replace it.
                self._stop_worker(repo)
                handle = None
            if handle is None:
                self._make_room(exclude=repo)
                handle = self._spawn(repo)
            handle.last_used = time.time()
            return {"socket": handle.sock, "pid": handle.proc.pid, "repo": repo, "version": self.version}

    def h_worker_stop(self, _conn: Connection, params):
        repo = self._validated_repo(params.get("repo"), must_exist=False)
        return {"stopped": self._stop_worker(repo)}

    def h_status(self, _conn: Connection, _params):
        with self._lock:
            handles = list(self.workers.values())
        rows = []
        for h in handles:
            row: dict[str, Any] = {"repo": h.repo, "pid": h.proc.pid, "alive": h.alive(), "started": h.started}
            if h.alive():
                try:
                    row.update(_worker_call(h.sock, "status", timeout=2.0))
                except (OSError, protocol.ProtocolError, protocol.RpcError):
                    row["unresponsive"] = True
            rows.append(row)
        rss = None
        try:
            import psutil  # pylint: disable=import-outside-toplevel
            rss = int(psutil.Process().memory_info().rss)
        except Exception:  # pylint: disable=broad-except
            pass
        return {"version": self.version, "pid": os.getpid(), "started": self.started, "rss_bytes": rss,
                "socket": self.server.path, "max_workers": paths.setting("max_workers"), "workers": rows}

    def h_shutdown(self, _conn: Connection, _params):
        threading.Thread(target=self.stop, daemon=True).start()
        return {"stopping": True}

    # -- workers --------------------------------------------------------------------------------
    @staticmethod
    def _validated_repo(raw: Any, must_exist: bool = True) -> str:
        """A repo root that exists and has a CogniRepo store — a request can never name an arbitrary path."""
        if not isinstance(raw, str) or not raw or len(raw) > 4096 or "\0" in raw:
            raise protocol.RpcError(protocol.INVALID_PARAMS, "repo must be a path string")
        repo = os.path.abspath(raw)
        if must_exist:
            from core.config import repo_registry  # pylint: disable=import-outside-toplevel
            if not os.path.isdir(repo) or not repo_registry.is_initialised(repo):
                raise protocol.RpcError(protocol.UNKNOWN_REPO, f"{repo} is not an initialised CogniRepo repo")
        return repo

    @staticmethod
    def _responsive(handle: "WorkerHandle") -> bool:
        try:
            return _worker_call(handle.sock, "ping", timeout=2.0) == "pong"
        except (OSError, protocol.ProtocolError, protocol.RpcError):
            return False

    def _make_room(self, exclude: str) -> None:
        limit = int(paths.setting("max_workers"))
        with self._lock:
            live = {r: h for r, h in self.workers.items() if h.alive() and r != exclude}
            self.workers = {r: h for r, h in self.workers.items() if h.alive()}
        while len(live) >= limit:
            idle = []
            for repo, h in live.items():
                try:
                    st = _worker_call(h.sock, "status", timeout=2.0)
                    if st.get("clients", 1) == 0:
                        idle.append((h.last_used, repo))
                except (OSError, protocol.ProtocolError, protocol.RpcError):
                    idle.append((h.last_used, repo))          # unresponsive: first to go
            if not idle:
                raise protocol.RpcError(protocol.TOO_MANY_WORKERS,
                                        f"{limit} repos are already active with connected agents")
            _, victim = min(idle)
            self._stop_worker(victim)
            live.pop(victim, None)

    def _spawn(self, repo: str) -> WorkerHandle:
        sock = paths.worker_socket(repo)
        log = os.path.join(paths.run_dir(), f"w-{paths.worker_key(repo)}.log")
        argv = paths.python_argv("interface.daemon.worker", "--repo", repo, "--socket", sock,
                                 "--idle-secs", str(paths.setting("worker_idle_secs")))
        with open(log, "ab") as logf:
            proc = subprocess.Popen(  # nosec B603 — fixed argv, no shell; repo is validated above
                argv, cwd=repo, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
                **procutil.detach_kwargs())
        handle = WorkerHandle(repo, sock, proc, log)
        deadline = time.time() + float(paths.setting("spawn_timeout_secs"))
        while time.time() < deadline:
            if proc.poll() is not None:
                raise protocol.RpcError(protocol.INTERNAL, f"the worker exited ({proc.returncode}): {_tail(log)}")
            try:
                _worker_call(sock, "hello", {"version": self.version}, timeout=2.0)
                with self._lock:
                    self.workers[repo] = handle
                return handle
            except (OSError, protocol.ProtocolError):
                time.sleep(0.15)
            except protocol.RpcError as exc:
                self._kill(proc)
                raise protocol.RpcError(protocol.INTERNAL, f"the worker refused the handshake: {exc.message}") from exc
        self._kill(proc)
        raise protocol.RpcError(protocol.INTERNAL, f"the worker did not come up in time: {_tail(log)}")

    @staticmethod
    def _kill(proc: subprocess.Popen) -> None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:  # pylint: disable=broad-except
            try:
                proc.kill()
            except OSError:
                pass

    def _stop_worker(self, repo: str) -> bool:
        with self._lock:
            handle = self.workers.pop(repo, None)
        if handle is None:
            return False
        try:
            _worker_call(handle.sock, "shutdown", timeout=2.0)
            handle.proc.wait(timeout=10)
        except Exception:  # pylint: disable=broad-except
            self._kill(handle.proc)
        return True

    # -- lifecycle ------------------------------------------------------------------------------
    def write_state(self) -> None:
        atomic_json_dump(paths.state_file(), {"pid": os.getpid(), "version": self.version, "started": self.started,
                                              "socket": self.server.path}, fsync=False)

    def stop(self) -> None:
        with self._lock:
            repos = list(self.workers)
        for repo in repos:
            self._stop_worker(repo)
        self.server.stop()
        try:
            os.unlink(paths.state_file())
        except OSError:
            pass

    def run(self) -> int:
        idle_exit = float(paths.setting("idle_exit_secs"))
        self.server.start()
        self.write_state()
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        signal.signal(signal.SIGINT, lambda *_: self.stop())
        logger.info("supervisor %s listening on %s (pid %s)", self.version, self.server.path, os.getpid())
        while not self.server.stopped:
            time.sleep(1.0)
            with self._lock:
                self.workers = {r: h for r, h in self.workers.items() if h.alive()}
                busy = bool(self.workers) or self.server.connection_count() > 0
            if busy:
                self.last_busy = time.time()
            elif time.time() - self.last_busy > idle_exit:
                logger.info("no workers for %.0fs: exiting", idle_exit)
                self.stop()
        return 0


def _tail(path: str, n: int = 300) -> str:
    try:
        with open(path, "rb") as fh:
            return fh.read()[-n:].decode("utf-8", "replace").strip().splitlines()[-1][:n]
    except (OSError, IndexError):
        return ""


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="python -m interface.daemon.supervisor").parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s %(message)s")
    if not paths.SUPPORTED:
        print("cognirepod: needs Unix domain sockets (not available here)", file=sys.stderr)
        return 2
    from filelock import FileLock, Timeout  # pylint: disable=import-outside-toplevel
    # A short wait absorbs the replace-an-older-daemon race: the old process has closed its socket but is still
    # finishing (and holding this lock for up to a second). A live daemon holds it indefinitely -> give up.
    lock = FileLock(paths.supervisor_lock(), timeout=8)
    try:
        lock.acquire()
    except Timeout:
        print("cognirepod: already running", file=sys.stderr)
        return 0
    try:
        return Supervisor().run()
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
