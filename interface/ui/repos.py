# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
``GET /api/v1/repos`` (#210): every repo in the global registry, with index and watcher state.

Strictly read-only. ``interface.cli.daemon.is_watcher_running_for_path`` is NOT used here: it creates
the repo's ``watchers/`` dir and deletes stale pid files, which a monitoring endpoint must never do
to repos it merely lists. This module reads the same files without touching them.
"""
from __future__ import annotations

import json
import os
from typing import Any

from core.config import repo_registry
from interface.ui.status import _STALE_HEARTBEAT_S, _read_json, indexer_status

_MAX_REPOS = 200


def _alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True      # exists, owned by someone else
    except OSError:
        return False
    return True


def watcher_state(repo_root: str, store: str) -> dict[str, Any]:
    """``{state, pid, heartbeat_age_s, last_reindex}`` from ``<store>/watchers`` without writing."""
    from interface.cli.daemon import _heartbeat_age  # pylint: disable=import-outside-toplevel
    wdir = os.path.join(store, "watchers")
    abs_root = os.path.abspath(repo_root)
    rec: dict[str, Any] | None = None
    try:
        names = sorted(n for n in os.listdir(wdir) if n.endswith(".json") and n != "heartbeat.json")
    except OSError:
        names = []
    for name in names:
        data = _read_json(os.path.join(wdir, name))
        if data and os.path.abspath(str(data.get("path", ""))) == abs_root and _alive(data.get("pid")):
            rec = data
            break
    hb = _read_json(os.path.join(wdir, "heartbeat"))
    if hb is not None and os.path.abspath(str(hb.get("path", ""))) != abs_root:
        hb = None
    age = _heartbeat_age(hb)
    if rec is None:
        state = "stopped"
    elif age is not None and age > _STALE_HEARTBEAT_S:
        state = "stale"
    else:
        state = "running"
    return {
        "state": state,
        "pid": rec.get("pid") if rec else None,
        "heartbeat_age_s": None if age is None else round(age, 1),
        "last_reindex": _read_json(os.path.join(store, "index", "last_watcher_reindex.json")),
    }


def hooks_installed(repo_root: str) -> bool:
    """True if the repo's git ``post-commit`` hook carries a cognirepo block."""
    try:
        with open(os.path.join(repo_root, ".git", "hooks", "post-commit"), encoding="utf-8", errors="ignore") as fh:
            return "cognirepo" in fh.read().lower()
    except OSError:
        return False


def auto_index(store: str) -> bool:
    cfg = _read_json(os.path.join(store, "config.json")) or {}
    watch = cfg.get("watch")
    return bool(watch.get("auto_enabled", True)) if isinstance(watch, dict) else True


def describe(row: dict[str, Any]) -> dict[str, Any]:
    root = row["path"]
    exists = os.path.isdir(root)
    if exists:   # resolve afresh: the store may have moved (hashed global dir -> local .cognirepo/)
        from core.config.paths import get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel
        store = get_cognirepo_dir_for_repo(root)
    else:
        store = row.get("store") or ""
    store_exists = bool(store) and os.path.isdir(store)
    out: dict[str, Any] = {
        "name": os.path.basename(root.rstrip(os.sep)) or root, "root": root, "store": store,
        "exists": exists, "first_seen": row.get("first_seen"), "last_seen": row.get("last_seen"),
        "indexed": False, "indexed_at": None, "git_commit": None,
        "watcher": {"state": "stopped", "pid": None, "heartbeat_age_s": None, "last_reindex": None},
        "hooks_installed": False, "auto_index": True,
    }
    if exists and store_exists:
        idx = indexer_status(root)
        out.update(indexed=idx["indexed"], indexed_at=idx["indexed_at"], git_commit=idx["git_commit"],
                   watcher=watcher_state(root, store), auto_index=auto_index(store))
    if exists:
        out["hooks_installed"] = hooks_installed(root)
    return out


def list_repos(current_root: str | None = None) -> list[dict[str, Any]]:
    """Registered repos (most recently seen first); the repo this server was started for is included
    even if it was never registered, so the console is never empty on a working install."""
    rows = repo_registry.load()[:_MAX_REPOS]
    if current_root:
        cur = os.path.abspath(current_root)
        if all(r["path"] != cur for r in rows):
            from core.config.paths import get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel
            store = get_cognirepo_dir_for_repo(cur)
            if os.path.isdir(store):
                rows.append({"path": cur, "store": store})
    return [describe(r) for r in rows]
