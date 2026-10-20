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
    }


def collect_status(repo_root: str, started_at: str, pid: int) -> dict[str, Any]:
    from core.config.version import __version__  # pylint: disable=import-outside-toplevel
    return {
        "api_version": API_VERSION,
        "version": __version__,
        "repo": {"root": repo_root, "name": os.path.basename(repo_root.rstrip(os.sep))},
        "daemon": daemon_status(repo_root),
        "mcp": mcp_status(),
        "indexer": indexer_status(repo_root),
        "ui": {"pid": pid, "started_at": started_at},
    }
