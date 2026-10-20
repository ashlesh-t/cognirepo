# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""CogniRepo processes working on the served repo, for ``GET /api/v1/processes`` (#212).

Read-only and best-effort. Three kinds are known, each from state it already leaves behind:
``ui`` (this server), ``watcher`` (the registered daemon, via the heartbeat) and ``mcp`` (one per
MCP session that has not ended and whose pid is alive, from the event log). Size figures come from
``psutil`` and are ``null`` when the process is gone or not inspectable.
"""
from __future__ import annotations

import os
from typing import Any

from core import events
from core.config import procutil


def _usage(pid: int) -> dict[str, int | None]:
    try:
        import psutil  # pylint: disable=import-outside-toplevel
        proc = psutil.Process(pid)
        with proc.oneshot():
            return {"rss_bytes": int(proc.memory_info().rss), "threads": int(proc.num_threads())}
    except Exception:  # pylint: disable=broad-except  # NoSuchProcess / AccessDenied / psutil missing
        return {"rss_bytes": None, "threads": None}


def _row(role: str, pid: int, state: str, **extra: Any) -> dict[str, Any]:
    return {"role": role, "pid": pid, "state": state, "heartbeat_age_s": None, "detail": None,
            "session_id": None, **_usage(pid), **extra}


def list_processes(repo_root: str, store: str) -> list[dict[str, Any]]:
    from interface.ui import repos  # pylint: disable=import-outside-toplevel
    rows = [_row("ui", os.getpid(), "running", detail="control API")]
    watcher = repos.watcher_state(repo_root, store)
    if watcher["state"] != "stopped" and isinstance(watcher.get("pid"), int):
        rows.append(_row("watcher", watcher["pid"], watcher["state"], heartbeat_age_s=watcher["heartbeat_age_s"]))
    seen = {(r["role"], r["pid"]) for r in rows}
    for sess in events.list_sessions(store, limit=200):
        pid = sess.get("pid")
        if sess["state"] == "closed" or not isinstance(pid, int) or ("mcp", pid) in seen:
            continue
        if not procutil.pid_alive(pid):
            continue
        seen.add(("mcp", pid))
        rows.append(_row("mcp", pid, sess["state"], detail=sess.get("client"), session_id=sess["id"]))
    return rows
