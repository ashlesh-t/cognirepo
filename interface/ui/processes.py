# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""CogniRepo processes working on the served repo, for ``GET /api/v1/processes`` (#212).

Read-only and best-effort. Three kinds are known, each from state it already leaves behind:
``ui`` (this server), ``watcher`` (the registered daemon, via the heartbeat) and ``mcp`` (one per
MCP session that has not ended and whose pid is alive, from the event log). MCP servers the event log
does not know about — started before pids were recorded, or with events disabled — are found by
scanning for ``serve`` processes whose working directory is the repo. Size figures come from
``psutil`` and are ``null`` when the process is gone or not inspectable.
"""
from __future__ import annotations

import os
import time
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


_SCAN_TTL_SECS = 5.0
_scan_cache: dict[str, tuple[float, list[int]]] = {}


def _is_serve(cmdline: list[str]) -> bool:
    """``cognirepo serve`` / ``python -m interface.cli.main serve`` (not ``serve-ui``-like look-alikes)."""
    return "serve" in cmdline and any(
        os.path.basename(a) in ("cognirepo", "cognirepo.exe") or a in ("interface.cli.main", "cognirepo")
        or a.endswith(("cognirepo/__main__.py", "interface/cli/main.py")) for a in cmdline)


def discover_serve_pids(repo_root: str) -> list[int]:
    """Pids of ``cognirepo serve`` processes whose cwd is ``repo_root``. Cached briefly; skips processes
    that cannot be inspected."""
    root = os.path.abspath(repo_root)
    now = time.monotonic()
    hit = _scan_cache.get(root)
    if hit and now - hit[0] < _SCAN_TTL_SECS:
        return list(hit[1])
    found: list[int] = []
    try:
        import psutil  # pylint: disable=import-outside-toplevel
        for proc in psutil.process_iter(["pid", "cmdline", "cwd"]):
            try:
                info = proc.info
                if info["pid"] != os.getpid() and info.get("cwd") and os.path.abspath(info["cwd"]) == root \
                        and _is_serve(info.get("cmdline") or []):
                    found.append(int(info["pid"]))
            except Exception:  # pylint: disable=broad-except  # AccessDenied / NoSuchProcess mid-scan
                continue
    except Exception:  # pylint: disable=broad-except
        found = []
    _scan_cache[root] = (now, found)
    return list(found)


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
    for pid in discover_serve_pids(repo_root):          # servers the event log does not know about
        if ("mcp", pid) not in seen and ("watcher", pid) not in seen:
            seen.add(("mcp", pid))
            rows.append(_row("mcp", pid, "running", detail="discovered by process scan"))
    return rows
