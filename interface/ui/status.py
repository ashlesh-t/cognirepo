# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Read-only status collection for ``GET /api/v1/status``.

Deliberately cheap and non-destructive: it reads small metadata files and the watcher
heartbeat only. It must NOT call ``ASTIndexer.load`` or construct ``LocalVectorDB`` — both
can rename/sweep live index files while another process is writing them (see the
concurrency audit in issue #129).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

API_VERSION = "1"
_STALE_HEARTBEAT_S = 120.0


def _read_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _store_dir(repo_root: str) -> str:
    from core.config.paths import get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel
    return str(get_cognirepo_dir_for_repo(repo_root))


def daemon_status(repo_root: str) -> dict[str, Any]:
    from interface.cli.daemon import (  # pylint: disable=import-outside-toplevel
        heartbeat_age_seconds_for_path, is_watcher_running_for_path,
    )
    rec = is_watcher_running_for_path(repo_root)
    age = heartbeat_age_seconds_for_path(repo_root)
    if rec is None:
        state = "stopped"
    elif age is not None and age > _STALE_HEARTBEAT_S:
        state = "stale"
    else:
        state = "running"
    return {
        "state": state,
        "pid": rec.get("pid") if rec else None,
        "name": rec.get("name") if rec else None,
        "heartbeat_age_s": None if age is None else round(age, 1),
    }


def readonly_daemon_status(repo_root: str) -> dict[str, Any]:
    """Like ``daemon_status`` but writes nothing (the daemon helpers delete stale pid files) — used for repos
    other than the one this server serves."""
    from interface.ui import repos  # pylint: disable=import-outside-toplevel
    w = repos.watcher_state(repo_root, _store_dir(repo_root))
    return {"state": w["state"], "pid": w["pid"], "name": None, "heartbeat_age_s": w["heartbeat_age_s"]}


def mcp_status() -> dict[str, Any]:
    """Tool inventory from the shipped manifest. (The MCP server is a stdio child of each
    agent client, so there is no single process to ping.)"""
    import interface.server as _server_pkg  # pylint: disable=import-outside-toplevel
    manifest = _read_json(str(Path(_server_pkg.__file__).parent / "manifest.json"))
    tools = [t.get("name") for t in (manifest or {}).get("tools", []) if isinstance(t, dict)]
    return {
        "transport": (manifest or {}).get("transport", "stdio"),
        "tool_count": len(tools),
        "tools": tools,
        "manifest_available": manifest is not None,
    }


def _graph_seq(repo_root: str) -> int:
    from data.graph import graph_seq  # pylint: disable=import-outside-toplevel
    return graph_seq.read(_store_dir(repo_root))


def auto_index(store: str) -> bool:
    from interface.ui.repos import auto_index as _auto  # pylint: disable=import-outside-toplevel
    return _auto(store)


def _graph_base_incomplete(repo_root: str, last_watch: dict | None) -> bool:
    """The watcher's latest batch skipped its graph save as the base was incomplete — unless a graph was
    written after that batch (a full ``index-repo``), which supersedes the record."""
    if not (last_watch or {}).get("graph_skipped"):
        return False
    store = _store_dir(repo_root)
    try:
        record = os.path.getmtime(os.path.join(store, "index", "last_watcher_reindex.json"))
        graph = os.path.getmtime(os.path.join(store, "graph", "graph.pkl"))
    except OSError:
        return True            # no graph on disk (or no record): still incomplete
    return graph <= record


def _watch_queue(repo_root: str) -> dict[str, Any] | None:
    """The file watcher's queue (depth, oldest wait, overflows, last batch), or None when no watcher is running."""
    from intelligence.indexer.watch_queue import read_status  # pylint: disable=import-outside-toplevel
    return read_status(_store_dir(repo_root))


def _store_bytes(repo_root: str) -> dict[str, int]:
    from core.store_stats import store_sizes  # pylint: disable=import-outside-toplevel
    return store_sizes(_store_dir(repo_root))


def indexer_status(repo_root: str) -> dict[str, Any]:
    idx = os.path.join(_store_dir(repo_root), "index")
    manifest = _read_json(os.path.join(idx, "manifest.json")) or {}
    last_watch = _read_json(os.path.join(idx, "last_watcher_reindex.json"))
    try:
        size = os.path.getsize(os.path.join(idx, "ast_index.json"))
    except OSError:
        size = None
    return {
        "indexed": bool(manifest) or size is not None,
        "indexed_at": manifest.get("indexed_at"),
        "git_commit": manifest.get("git_commit"),
        "ast_index_bytes": size,
        "last_watcher_reindex": last_watch,
        "graph_seq": _graph_seq(repo_root),
        # The watcher refused to save the graph on its latest batch because the base graph is not a
        # complete one: one full `cognirepo index-repo .` fixes it (#211). False until a batch has run.
        "graph_base_incomplete": _graph_base_incomplete(repo_root, last_watch),
        "auto_index": auto_index(_store_dir(repo_root)),
        "store_bytes": _store_bytes(repo_root),
        "watch_queue": _watch_queue(repo_root),
    }


def collect_status(repo_root: str, started_at: str, pid: int, *, served: bool = True) -> dict[str, Any]:
    from core.config.version import __version__  # pylint: disable=import-outside-toplevel
    return {
        "api_version": API_VERSION,
        "version": __version__,
        "repo": {"root": repo_root, "name": os.path.basename(repo_root.rstrip(os.sep))},
        "daemon": daemon_status(repo_root) if served else readonly_daemon_status(repo_root),
        "mcp": mcp_status(),
        "indexer": indexer_status(repo_root),
        "ui": {"pid": pid, "started_at": started_at},
    }
