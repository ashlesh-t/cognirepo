# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""A detached ``cognirepo`` subprocess whose state lives in files, so it survives a UI-server restart (#213).

Same model as the ``index`` service in ``services.py`` — a run record while live, a result file after, the
child's output in a log — as a small reusable class. A fixed argv is the only thing that ever runs; nothing from
a request reaches it. ``classify(returncode, log_text)`` turns the outcome into
``(result, reason, summary)``: ``ok`` | ``busy`` (retryable) | ``failed``.
"""
from __future__ import annotations

import json
import os
import subprocess  # nosec B404 — fixed argv only
import time
from typing import Any, Callable

from core.config import procutil
from core.config.atomic import atomic_json_dump

MAX_AGE_SECS = 6 * 3600          # a run record older than this is treated as dead (pid-reuse guard)
EX_TEMPFAIL = 75                 # the CLI's "store busy" exit code


class FileJob:
    def __init__(self, name: str, directory: str, classify: Callable[[int | None, str], tuple[str, str | None, Any]]) -> None:
        self.name = name
        self.dir = directory
        self.classify = classify
        self.proc: subprocess.Popen | None = None

    # -- files ----------------------------------------------------------------------------------
    def _f(self, suffix: str) -> str:
        return os.path.join(self.dir, f"ui-{self.name}{suffix}")

    @staticmethod
    def _read(path: str) -> dict | None:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def _log(self) -> str:
        try:
            with open(self._f(".log"), encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return ""

    # -- state ----------------------------------------------------------------------------------
    def live(self) -> dict | None:
        rec = self._read(self._f("-run.json"))
        if not rec:
            return None
        if self.proc is not None and self.proc.pid == rec.get("pid"):
            return rec if self.proc.poll() is None else None
        pid = rec.get("pid")
        fresh = time.time() - float(rec.get("started_epoch", 0)) < MAX_AGE_SECS
        return rec if isinstance(pid, int) and fresh and procutil.pid_alive(pid) else None

    def settle(self) -> None:
        """If a recorded run has ended, classify and persist it (once). Callers hold the service lock."""
        rec = self._read(self._f("-run.json"))
        if not rec or self.live() is not None:
            return
        rc = self.proc.poll() if self.proc is not None and self.proc.pid == rec.get("pid") else None
        text = self._log()
        result, reason, summary = self.classify(rc, text)
        last = {"result": result, "reason": reason, "exit_code": rc, "retryable": result == "busy",
                "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "duration_s": round(max(0.0, time.time() - float(rec.get("started_epoch", time.time()))), 1),
                "detail": " | ".join([ln.strip() for ln in text.splitlines() if ln.strip()][-2:])[:300] or None,
                "summary": summary}
        try:
            atomic_json_dump(self._f("-last.json"), last, fsync=False)
        except OSError:
            pass
        try:
            os.remove(self._f("-run.json"))
        except OSError:
            pass
        self.proc = None

    def view(self) -> dict[str, Any]:
        self.settle()
        running = self.live() is not None
        last = None if running else self._read(self._f("-last.json"))
        summary = (last or {}).pop("summary", None) if last else None
        return {"state": "running" if running else "idle", "last_run": last, "summary": summary}

    def start(self, argv: list[str], cwd: str, env: dict[str, str] | None = None) -> bool:
        """Spawn the job unless one is live. Returns True if a new run started."""
        self.settle()
        if self.live() is not None:
            return False
        os.makedirs(self.dir, exist_ok=True)
        for stale in (self._f("-last.json"),):
            try:
                os.remove(stale)
            except OSError:
                pass
        with open(self._f(".log"), "wb") as log:     # truncated per run: it describes only the latest one
            self.proc = subprocess.Popen(  # nosec B603 — fixed argv, no shell
                argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                env={**os.environ, **(env or {})}, **procutil.detach_kwargs())
        atomic_json_dump(self._f("-run.json"), {"pid": self.proc.pid, "started_epoch": time.time()}, fsync=False)
        return True
