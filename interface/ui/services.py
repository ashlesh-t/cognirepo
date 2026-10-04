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

import os
import subprocess  # nosec B404 — fixed argv only, see _spawn_watcher
import sys
import threading
import time
from typing import Any

ALLOWED: tuple[str, ...] = ("watcher", "metrics")


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
        self._lock = threading.Lock()

    # ── watcher ──────────────────────────────────────────────────────────────
    def _watcher_record(self) -> dict | None:
        from interface.cli.daemon import is_watcher_running_for_path  # pylint: disable=import-outside-toplevel
        return is_watcher_running_for_path(self.repo_root)

    def _spawn_watcher(self) -> None:
        if not sys.platform.startswith("linux"):
            raise ServiceError(501, "unsupported_platform", "the watcher daemon is supported on Linux only")
        # Fixed argv; nothing from the request reaches it.
        argv = [sys.executable, "-m", "interface.cli.main", "watch", "--path", self.repo_root, "--ensure-running"]
        subprocess.Popen(  # nosec B603 — fixed argv, no shell
            argv, cwd=self.repo_root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )

    def _watcher_status(self) -> dict[str, Any]:
        rec = self._watcher_record()
        return {"name": "watcher", "state": "running" if rec else "stopped", "pid": rec.get("pid") if rec else None}

    def _watcher_start(self) -> dict[str, Any]:
        if self._watcher_record():
            return {**self._watcher_status(), "changed": False}
        self._spawn_watcher()
        return {"name": "watcher", "state": "starting", "pid": None, "changed": True}

    def _watcher_stop(self) -> dict[str, Any]:
        rec = self._watcher_record()
        if not rec:
            return {**self._watcher_status(), "changed": False}
        from interface.cli.daemon import _is_alive, stop_watcher  # pylint: disable=import-outside-toplevel
        pid = rec["pid"]
        stop_watcher(str(pid))
        deadline = time.monotonic() + 5.0  # stop_watcher only *sends* SIGTERM (see #126)
        while time.monotonic() < deadline and _is_alive(pid):
            time.sleep(0.1)
        return {"name": "watcher", "state": "stopped" if not _is_alive(pid) else "stopping", "pid": pid, "changed": True}

    # ── metrics (in-process /metrics server, loopback only) ──────────────────
    def _metrics_status(self) -> dict[str, Any]:
        running = self._metrics_server is not None
        port = self._metrics_server.server_address[1] if running else None
        return {"name": "metrics", "state": "running" if running else "stopped", "port": port}

    def _metrics_start(self) -> dict[str, Any]:
        with self._lock:
            if self._metrics_server is not None:
                return {**self._metrics_status(), "changed": False}
            from interface.cli.metrics_server import create_metrics_server  # pylint: disable=import-outside-toplevel
            try:
                server = create_metrics_server("127.0.0.1", self.metrics_port)
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

    # ── public API ───────────────────────────────────────────────────────────
    def status(self, name: str | None = None) -> Any:
        if name is None:
            return [self.status(n) for n in ALLOWED]
        self._check(name)
        return self._watcher_status() if name == "watcher" else self._metrics_status()

    def start(self, name: str) -> dict[str, Any]:
        self._check(name)
        return self._watcher_start() if name == "watcher" else self._metrics_start()

    def stop(self, name: str) -> dict[str, Any]:
        self._check(name)
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
