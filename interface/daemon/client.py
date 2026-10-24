# SPDX-FileCopyrightText: 2026 Ashlesh T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Talking to the daemon: find or start the supervisor, get a repo worker, hold a session on it (#116).

Every failure surfaces as ``DaemonUnavailable`` and means "carry on in-process" — a client never waits on a wedged
daemon: connects and requests have timeouts, and a supervisor that does not answer in time is treated as absent.
"""
from __future__ import annotations

import os
import socket
import subprocess  # nosec B404 — fixed argv only
import time
from typing import Any

from core.config import procutil
from interface.daemon import paths, protocol


class DaemonUnavailable(Exception):
    """The daemon cannot be used right now (not enabled, not startable, wedged, refused). Fall back in-process."""


def _version() -> str:
    from core.config.version import __version__  # pylint: disable=import-outside-toplevel
    return __version__


def connect(path: str, timeout: float | None = None) -> socket.socket:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(float(paths.setting("connect_timeout_secs")) if timeout is None else timeout)
    try:
        s.connect(path)
    except OSError:
        s.close()
        raise
    return s


def rpc(path: str, method: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
    """One-shot request on a fresh connection."""
    s = connect(path, timeout)
    try:
        if timeout is not None:
            s.settimeout(timeout)
        return protocol.call(s, method, params)
    finally:
        s.close()


def supervisor_info() -> dict[str, Any] | None:
    """``hello`` from a running supervisor, or ``None`` if there is none (or it does not answer)."""
    try:
        return rpc(paths.supervisor_socket(), "hello", {"version": _version()})
    except (OSError, protocol.ProtocolError, protocol.RpcError, paths.RunDirError):
        return None


def _spawn_supervisor() -> None:
    with open(paths.log_file(), "ab") as log:
        subprocess.Popen(  # nosec B603 — fixed argv, no shell
            paths.python_argv("interface.daemon.supervisor"), stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT, **procutil.detach_kwargs())


def _wait(predicate, timeout: float, step: float = 0.1) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


def ensure_supervisor() -> dict[str, Any]:
    """A running supervisor of OUR version, started (and an older one replaced) if needed."""
    if not paths.SUPPORTED:
        raise DaemonUnavailable("this platform has no Unix domain sockets")
    try:
        paths.run_dir()
        paths.supervisor_socket()                    # an unusable run dir (e.g. a too-long socket path) fails here, fast
        info = supervisor_info()
        if info is not None and info.get("version") == _version():
            return info
        from filelock import FileLock, Timeout  # pylint: disable=import-outside-toplevel
        try:
            with FileLock(paths.start_lock(), timeout=float(paths.setting("spawn_timeout_secs"))):
                info = supervisor_info()             # someone else may have started it while we waited
                if info is not None and info.get("version") != _version():
                    _shutdown_supervisor()
                    info = None
                if info is None:
                    _spawn_supervisor()
                    if not _wait(lambda: supervisor_info() is not None, 20.0):
                        raise DaemonUnavailable("the daemon did not start (see " + paths.log_file() + ")")
                    info = supervisor_info()
        except Timeout as exc:
            raise DaemonUnavailable("another client is starting the daemon and it is taking too long") from exc
        if info is None or info.get("version") != _version():
            raise DaemonUnavailable("the daemon is running a different version and could not be replaced")
        return info
    except paths.RunDirError as exc:
        raise DaemonUnavailable(str(exc)) from exc


def _shutdown_supervisor() -> None:
    try:
        rpc(paths.supervisor_socket(), "shutdown", timeout=3.0)
    except (OSError, protocol.ProtocolError, protocol.RpcError):
        pass
    _wait(lambda: supervisor_info() is None, 15.0)
    _wait(_lock_free, 15.0)


def _lock_free() -> bool:
    """True once no supervisor process holds ``daemon.lock`` (the socket vanishes a moment before the process exits)."""
    from filelock import FileLock, Timeout  # pylint: disable=import-outside-toplevel
    probe = FileLock(paths.supervisor_lock(), timeout=0)
    try:
        probe.acquire()
    except Timeout:
        return False
    probe.release()
    return True


def worker_info(repo: str) -> dict[str, Any]:
    """Ask the supervisor for ``repo``'s worker (starting it); ``{"socket", "pid", ...}``."""
    ensure_supervisor()
    try:
        return rpc(paths.supervisor_socket(), "worker.ensure", {"repo": repo},
                   timeout=float(paths.setting("spawn_timeout_secs")) + 5.0)
    except protocol.RpcError as exc:
        raise DaemonUnavailable(exc.message) from exc
    except (OSError, protocol.ProtocolError) as exc:
        raise DaemonUnavailable(f"the daemon did not answer: {exc}") from exc


class WorkerLink:
    """One agent session on a repo worker: a connection plus the session it opened."""

    def __init__(self, repo: str, client: str | None = None) -> None:
        self.repo = os.path.abspath(repo)
        self.client = client
        self.sock: socket.socket | None = None
        self.info: dict[str, Any] = {}
        self.session_id: str | None = None
        self._next_id = 3

    def open(self) -> "WorkerLink":
        info = worker_info(self.repo)
        try:
            sock = connect(info["socket"])
            sock.settimeout(float(paths.setting("request_timeout_secs")))
            try:
                protocol.call(sock, "hello", {"version": _version()})
                opened = protocol.call(sock, "session.open", {"client": self.client}, 2)
            except Exception:
                sock.close()
                raise
        except protocol.RpcError as exc:
            if exc.code == protocol.VERSION_MISMATCH:        # an older worker outlived an upgrade: replace it
                try:
                    rpc(paths.supervisor_socket(), "worker.stop", {"repo": self.repo}, timeout=15.0)
                except (OSError, protocol.ProtocolError, protocol.RpcError):
                    pass
            raise DaemonUnavailable(exc.message) from exc
        except (OSError, protocol.ProtocolError, KeyError) as exc:
            raise DaemonUnavailable(f"could not reach the worker: {exc}") from exc
        self.sock, self.info, self.session_id = sock, info, opened.get("session_id")
        self._next_id = 3
        return self

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if self.sock is None:
            raise DaemonUnavailable("not connected")
        self._next_id += 1
        return protocol.call(self.sock, method, params, self._next_id)

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None


def status(timeout: float = 5.0) -> dict[str, Any] | None:
    """The supervisor's ``status`` (workers included), or ``None`` if it is not running. Never starts anything."""
    if not paths.SUPPORTED:
        return None
    try:
        return rpc(paths.supervisor_socket(), "status", timeout=timeout)
    except (OSError, protocol.ProtocolError, protocol.RpcError, paths.RunDirError):
        return None


def stop() -> bool:
    """Stop the supervisor (and with it every worker). True if one was running."""
    if supervisor_info() is None:
        return False
    _shutdown_supervisor()
    return True
