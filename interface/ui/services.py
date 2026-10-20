# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Allowlisted service control for ``POST /api/v1/services/{name}/{start|stop}``.

There is no generic "run this command": each service name maps to code in this module with a
FIXED argv and no client-supplied arguments. Names outside ``ALLOWED`` are rejected before
anything else happens.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess  # nosec B404 — fixed argv only, see _spawn_watcher
import sys
import threading
import time
from typing import Any

from core.config import procutil
from core.config.atomic import atomic_json_dump

ALLOWED: tuple[str, ...] = ("watcher", "metrics", "insights", "index", "hooks")

_START_WAIT_SECS = 2.0
_STOP_WAIT_SECS = 8.0
_KILL_WAIT_SECS = 3.0
_HOOKS_TIMEOUT_SECS = 30.0
_INDEX_MAX_AGE_SECS = 6 * 3600     # a recorded run older than this is treated as dead (pid reuse guard)
_EX_TEMPFAIL = 75      # `store busy` exit code of the CLI (see interface/cli/main.py)


class ServiceError(Exception):
    """A service action failed in a way the client should see."""

    def __init__(self, status: int, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.status = status
        self.code = code
        self.message = message or code


class ServiceManager:
    """Start/stop/status for the allowlisted services of one repo."""

    def __init__(self, repo_root: str, metrics_port: int = 9090) -> None:
        self.repo_root = os.path.abspath(repo_root)
        self.metrics_port = metrics_port
        self._metrics_server = None
        self._metrics_thread: threading.Thread | None = None
        self._insights_proc: subprocess.Popen | None = None
        self._index_proc: subprocess.Popen | None = None
        self._index_last: dict[str, Any] | None = None
        self._lock = threading.Lock()

    # ── watcher ──────────────────────────────────────────────────────────────
    def _watcher_record(self) -> dict | None:
        from interface.cli.daemon import is_watcher_running_for_path  # pylint: disable=import-outside-toplevel
        return is_watcher_running_for_path(self.repo_root)

    def _watcher_log_path(self) -> str:
        from core.config.paths import get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel
        return os.path.join(get_cognirepo_dir_for_repo(self.repo_root), "watchers", "ui-start.log")

    def _initialised(self) -> bool:
        from core.config.paths import get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel
        return os.path.isfile(os.path.join(get_cognirepo_dir_for_repo(self.repo_root), "config.json"))

    def _spawn_watcher(self) -> subprocess.Popen:
        """Run ``watch --ensure-running`` with its output captured (it used to be discarded, so a
        failure was invisible). Fixed argv; nothing from the request reaches it."""
        argv = [sys.executable, "-m", "interface.cli.main", "watch", "--path", self.repo_root, "--ensure-running"]
        log_path = self._watcher_log_path()
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "wb") as log:    # truncated per attempt: it describes only the latest one
            return subprocess.Popen(  # nosec B603 — fixed argv, no shell
                argv, cwd=self.repo_root, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, **procutil.detach_kwargs(),
            )

    def _log_tail(self) -> str:
        try:
            with open(self._watcher_log_path(), "rb") as fh:
                lines = fh.read()[-2000:].decode("utf-8", "replace").strip().splitlines()
        except OSError:
            return ""
        return lines[-1][:300] if lines else ""

    @staticmethod
    def _failed(name: str, reason: str, detail: str = "", **extra: Any) -> dict[str, Any]:
        return {"name": name, "state": "failed", "pid": None, "changed": False, "reason": reason,
                "detail": detail, **extra}

    def _watcher_status(self) -> dict[str, Any]:
        rec = self._watcher_record()
        return {"name": "watcher", "state": "running" if rec else "stopped", "pid": rec.get("pid") if rec else None}

    def _watcher_start(self) -> dict[str, Any]:
        if self._watcher_record():
            return {**self._watcher_status(), "changed": False}
        if os.environ.get("COGNIREPO_NO_WATCHER"):
            return self._failed("watcher", "disabled_by_env", "COGNIREPO_NO_WATCHER is set")
        if not self._initialised():
            return self._failed("watcher", "not_initialised", "no .cognirepo/ for this repo; run `cognirepo init`")
        try:
            proc = self._spawn_watcher()
        except OSError as exc:
            return self._failed("watcher", "spawn_failed", str(exc)[:300])
        # The launcher hands off to a detached watcher and exits; wait briefly so the response says
        # what happened instead of promising "starting".
        deadline = time.monotonic() + _START_WAIT_SECS
        while time.monotonic() < deadline:
            rec = self._watcher_record()
            if rec:
                self._reap_later(proc)
                return {"name": "watcher", "state": "running", "pid": rec.get("pid"), "changed": True}
            rc = proc.poll()
            if rc not in (None, 0):
                return self._failed("watcher", "spawn_failed", self._log_tail() or f"launcher exited with {rc}")
            time.sleep(0.1)
        self._reap_later(proc)
        # Slow to register (loading the index) is not a failure — but say so rather than "running".
        return {"name": "watcher", "state": "starting", "pid": None, "changed": True}

    @staticmethod
    def _reap_later(proc: subprocess.Popen) -> None:
        if proc.poll() is None:
            threading.Thread(target=proc.wait, daemon=True, name="cognirepo-ui-reap").start()

    def _watcher_stop(self) -> dict[str, Any]:
        rec = self._watcher_record()
        if not rec:
            return {**self._watcher_status(), "changed": False}
        from interface.cli.daemon import stop_watcher_and_wait  # pylint: disable=import-outside-toplevel
        pid = rec["pid"]
        # Same stop as `cognirepo list --stop`: SIGTERM, then SIGKILL if it ignores it, and the
        # registration is removed only once the process is really gone. Bounded waits keep the request short.
        outcome = stop_watcher_and_wait(str(pid), timeout=_STOP_WAIT_SECS, kill_wait=_KILL_WAIT_SECS)
        if outcome in ("stopped", "killed"):
            return {"name": "watcher", "state": "stopped", "pid": pid, "changed": True,
                    **({"detail": "needed SIGKILL"} if outcome == "killed" else {})}
        if outcome == "not_found":
            return {**self._watcher_status(), "changed": False}
        if outcome == "embedded":
            raise ServiceError(409, "embedded_watcher",
                               "this watcher is a thread inside an MCP server; stop that agent session instead")
        return {**self._failed("watcher", "stop_failed", "the watcher is still alive after SIGTERM/SIGKILL"),
                "pid": pid, "changed": True}

    # ── metrics (in-process /metrics server, loopback only) ──────────────────
    def _metrics_status(self) -> dict[str, Any]:
        running = self._metrics_server is not None
        port = self._metrics_server.server_address[1] if running else None
        return {"name": "metrics", "state": "running" if running else "stopped", "port": port}

    def _metrics_start(self) -> dict[str, Any]:
        with self._lock:
            if self._metrics_server is not None:
                return {**self._metrics_status(), "changed": False}
            if importlib.util.find_spec("prometheus_client") is None:    # the scrape endpoint would 501
                return self._failed("metrics", "dependency_missing", "prometheus_client is not installed")
            from interface.cli.metrics_server import create_metrics_server  # pylint: disable=import-outside-toplevel
            try:
                server = create_metrics_server("127.0.0.1", self.metrics_port, self.repo_root)
            except OSError as exc:
                raise ServiceError(409, "port_in_use", f"cannot bind 127.0.0.1:{self.metrics_port}: {exc}") from exc
            thread = threading.Thread(target=server.serve_forever, daemon=True, name="cognirepo-ui-metrics")
            thread.start()
            self._metrics_server, self._metrics_thread = server, thread
            return {**self._metrics_status(), "changed": True}

    def _metrics_stop(self) -> dict[str, Any]:
        with self._lock:
            server = self._metrics_server
            if server is None:
                return {**self._metrics_status(), "changed": False}
            server.shutdown()
            server.server_close()
            self._metrics_server = self._metrics_thread = None
            return {**self._metrics_status(), "changed": True}

    # ── insights (regenerate the report; one run at a time) ──────────────────
    def _insights_running(self) -> bool:
        proc = self._insights_proc
        return proc is not None and proc.poll() is None

    def _insights_status(self) -> dict[str, Any]:
        return {"name": "insights", "state": "running" if self._insights_running() else "idle"}

    def _insights_start(self) -> dict[str, Any]:
        """Regenerate the report with the existing generator (`cognirepo insights`) — fixed argv,
        nothing from the request reaches it; the UI process itself never imports the collector."""
        with self._lock:
            if self._insights_running():
                return {**self._insights_status(), "changed": False}
            argv = [sys.executable, "-m", "interface.cli.main", "insights"]
            self._insights_proc = subprocess.Popen(  # nosec B603 — fixed argv, no shell
                argv, cwd=self.repo_root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, **procutil.detach_kwargs(),
            )
            return {**self._insights_status(), "changed": True}

    # ── index (incremental only: `index-repo --changed-only`; one run at a time) ─
    def _store(self) -> str:
        from core.config.paths import get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel
        return str(get_cognirepo_dir_for_repo(self.repo_root))

    def _index_log_path(self) -> str:
        return os.path.join(self._store(), "watchers", "ui-index.log")

    def _index_progress_path(self) -> str:
        return os.path.join(self._store(), "watchers", "ui-index-progress.json")

    def _index_tail(self, lines: int = 1) -> str:
        try:
            with open(self._index_log_path(), "rb") as fh:
                text = fh.read()[-4000:].decode("utf-8", "replace")
        except OSError:
            return ""
        kept = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return " | ".join(kept[-lines:])[:400]

    def _index_progress(self) -> dict[str, int] | None:
        try:
            with open(self._index_progress_path(), encoding="utf-8") as fh:
                data = json.load(fh)
            return {"done": int(data["done"]), "total": int(data["total"])}
        except (OSError, ValueError, KeyError, TypeError):
            return None

    # Run state is file-backed so a restarted UI server still knows about a run it did not start and
    # keeps the last result: ``ui-index-run.json`` while a run is live, ``ui-index-last.json`` after.
    def _index_file(self, name: str) -> str:
        return os.path.join(self._store(), "watchers", name)

    @staticmethod
    def _read_json_file(path: str) -> dict | None:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def _index_live(self) -> dict | None:
        """The run record if a run is still alive (ours or inherited from a previous UI server)."""
        rec = self._read_json_file(self._index_file("ui-index-run.json"))
        if not rec:
            return None
        proc = self._index_proc
        if proc is not None and proc.pid == rec.get("pid"):
            return rec if proc.poll() is None else None
        pid = rec.get("pid")
        fresh = time.time() - float(rec.get("started_epoch", 0)) < _INDEX_MAX_AGE_SECS   # guards pid reuse
        return rec if isinstance(pid, int) and fresh and procutil.pid_alive(pid) else None

    def _index_settle(self) -> None:
        """If a recorded run has ended, classify it and persist the result (once). Callers hold the lock."""
        rec = self._read_json_file(self._index_file("ui-index-run.json"))
        if not rec or self._index_live() is not None:
            return
        proc = self._index_proc
        rc = proc.poll() if proc is not None and proc.pid == rec.get("pid") else None   # None: not our child
        try:
            with open(self._index_log_path(), encoding="utf-8", errors="replace") as fh:
                full = fh.read()
        except OSError:
            full = ""
        finished_ok = rc == 0 or (rc is None and ("Re-indexed" in full or "No changed files" in full))
        if finished_ok:
            result, reason = "ok", None
        elif rc == _EX_TEMPFAIL or "already running" in full or "writer lease" in full:
            result, reason = "busy", "store_busy"       # another writer holds the store: retry, not an error
        elif "not updating the graph" in full:
            result, reason = "failed", "base_incomplete"
        else:
            result, reason = "failed", "index_failed"
        self._index_last = {
            "result": result, "reason": reason, "exit_code": rc, "retryable": result == "busy",
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "duration_s": round(max(0.0, time.time() - float(rec.get("started_epoch", time.time()))), 1),
            "detail": self._index_tail(3) or None,
        }
        try:
            atomic_json_dump(self._index_file("ui-index-last.json"), self._index_last, fsync=False)
        except OSError:
            pass
        try:
            os.remove(self._index_file("ui-index-run.json"))
        except OSError:
            pass
        self._index_proc = None

    def _index_view(self) -> dict[str, Any]:
        self._index_settle()
        running = self._index_live() is not None
        last = self._index_last or (None if running else self._read_json_file(self._index_file("ui-index-last.json")))
        return {"name": "index", "state": "running" if running else "idle",
                "progress": self._index_progress() if running else None,
                "last_run": dict(last) if last else None}

    def _index_status(self) -> dict[str, Any]:
        with self._lock:
            return self._index_view()

    def _index_start(self) -> dict[str, Any]:
        """Incremental re-index of what git reports as changed — fixed argv, nothing from the request
        reaches it. A full re-index is deliberately not exposed here."""
        with self._lock:
            self._index_settle()
            if self._index_live() is not None:
                return {**self._index_view(), "changed": False}
            if not self._initialised():
                return self._failed("index", "not_initialised", "no .cognirepo/ for this repo; run `cognirepo init`")
            argv = [sys.executable, "-m", "interface.cli.main", "index-repo", "--changed-only"]
            log_path = self._index_log_path()
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            for stale in (self._index_progress_path(), self._index_file("ui-index-last.json")):
                try:
                    os.remove(stale)
                except OSError:
                    pass
            env = {**os.environ, "COGNIREPO_PROGRESS_FILE": self._index_progress_path()}
            try:
                with open(log_path, "wb") as log:    # truncated per run: it describes only the latest one
                    self._index_proc = subprocess.Popen(  # nosec B603 — fixed argv, no shell
                        argv, cwd=self.repo_root, stdin=subprocess.DEVNULL, stdout=log,
                        stderr=subprocess.STDOUT, env=env, **procutil.detach_kwargs(),
                    )
            except OSError as exc:
                return self._failed("index", "spawn_failed", str(exc)[:300])
            self._index_last = None
            atomic_json_dump(self._index_file("ui-index-run.json"),
                             {"pid": self._index_proc.pid, "started_epoch": time.time()}, fsync=False)
            return {**self._index_view(), "changed": True}

    # ── hooks (install / uninstall the git hooks) ────────────────────────────
    def _hooks_status(self) -> dict[str, Any]:
        from interface.ui.repos import hooks_installed  # pylint: disable=import-outside-toplevel
        return {"name": "hooks", "state": "installed" if hooks_installed(self.repo_root) else "not_installed"}

    def _hooks_run(self, verb: str) -> dict[str, Any]:
        """``install-hooks`` / ``uninstall-hooks`` with a fixed argv, in the served repo."""
        was = self._hooks_status()["state"]
        want = "installed" if verb == "install-hooks" else "not_installed"
        if was == want:
            return {**self._hooks_status(), "changed": False}
        if not os.path.isdir(os.path.join(self.repo_root, ".git")):
            return self._failed("hooks", "not_a_git_repo", "no .git/ directory in this repo")
        try:
            proc = subprocess.run(  # nosec B603 — fixed argv, no shell
                [sys.executable, "-m", "interface.cli.main", verb], cwd=self.repo_root, capture_output=True,
                text=True, timeout=_HOOKS_TIMEOUT_SECS, check=False, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return self._failed("hooks", "spawn_failed", str(exc)[:300])
        if proc.returncode != 0:
            lines = (proc.stderr or proc.stdout or "").strip().splitlines()
            return self._failed("hooks", f"{verb.replace('-', '_')}_failed", lines[-1][:300] if lines else "")
        return {**self._hooks_status(), "changed": True}

    # ── public API ───────────────────────────────────────────────────────────
    def status(self, name: str | None = None) -> Any:
        if name is None:
            return [self.status(n) for n in ALLOWED]
        self._check(name)
        return {"watcher": self._watcher_status, "metrics": self._metrics_status,
                "insights": self._insights_status, "index": self._index_status,
                "hooks": self._hooks_status}[name]()

    def start(self, name: str) -> dict[str, Any]:
        self._check(name)
        return {"watcher": self._watcher_start, "metrics": self._metrics_start,
                "insights": self._insights_start, "index": self._index_start,
                "hooks": lambda: self._hooks_run("install-hooks")}[name]()

    def stop(self, name: str) -> dict[str, Any]:
        self._check(name)
        if name in ("insights", "index"):
            raise ServiceError(409, "not_stoppable", "a run finishes on its own")
        if name == "hooks":
            return self._hooks_run("uninstall-hooks")
        return self._watcher_stop() if name == "watcher" else self._metrics_stop()

    def shutdown(self) -> None:
        """Stop in-process services when the UI server exits."""
        if self._metrics_server is not None:
            self._metrics_stop()

    @staticmethod
    def allowed() -> tuple[str, ...]:
        return ALLOWED

    @staticmethod
    def _check(name: str) -> None:
        if name not in ALLOWED:
            raise ServiceError(404, "unknown_service", f"unknown service {name!r}")
