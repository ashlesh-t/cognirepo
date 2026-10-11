# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Deletion tombstones (COGNIREPO-169).

When a file is deleted, hiding it and purging it are two separate steps:

* **hide** — immediately. ``mark()`` writes ``{path: deleted_at}`` to ``index/tombstones.json``;
  every retrieval path asks ``hidden()`` and skips those files, so a deleted reference is never
  served. It is one small file read-modify-written under ``store_lock()``, so a hook process that
  exits does not lose it.
* **purge** — later, once the entry is older than ``indexing.delete_grace_secs`` (default 60).
  ``ASTIndexer.purge_tombstones()`` removes the file's vectors, graph nodes and index records
  in one batch. If the path reappears inside the window (editor atomic save, branch switch,
  ``git mv``) ``clear()`` drops the tombstone and nothing is purged or re-embedded.
"""
import json
import logging
import os
import time
from typing import Iterable

from core.config.atomic import atomic_write
from core.config.lock import store_lock
from core.config.paths import get_path

log = logging.getLogger(__name__)

__all__ = ["mark", "clear", "load", "hidden", "expired", "grace_secs", "DEFAULT_GRACE_SECS"]

DEFAULT_GRACE_SECS = 60.0

_cache: "tuple[tuple, dict[str, float]] | None" = None   # (path, stamp) -> parsed


def _path() -> str:
    return get_path("index/tombstones.json")


def grace_secs() -> float:
    """``indexing.delete_grace_secs`` from config.json (default 60)."""
    try:
        with open(get_path("config.json"), encoding="utf-8") as f:
            return max(0.0, float(json.load(f).get("indexing", {}).get("delete_grace_secs", DEFAULT_GRACE_SECS)))
    except Exception:  # pylint: disable=broad-except
        return DEFAULT_GRACE_SECS


def load() -> dict[str, float]:
    """``{rel_path: deleted_at}``; empty if absent or unreadable. Lock-free, cached by file stamp."""
    global _cache  # pylint: disable=global-statement
    path = _path()
    try:
        st = os.stat(path)
    except OSError:
        return {}
    key = (path, st.st_mtime_ns, st.st_size)
    if _cache is not None and _cache[0] == key:
        return _cache[1]
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        data = {str(k): float(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}       # a torn/garbled file hides nothing; never block reads on it
    _cache = (key, data)
    return data


def hidden() -> frozenset:
    """Files that must not be served (tombstoned and not yet purged)."""
    data = load()
    return frozenset(data) if data else frozenset()


def _write(data: dict[str, float]) -> None:
    if data:
        atomic_write(_path(), json.dumps(data, sort_keys=True))
    else:
        try:
            os.unlink(_path())
        except OSError:
            pass


def mark(paths: Iterable[str], now: "float | None" = None) -> None:
    """Tombstone ``paths``. A path that is already tombstoned keeps its original time."""
    paths = list(paths)
    if not paths:
        return
    stamp = time.time() if now is None else now
    with store_lock():
        data = dict(load())
        for p in paths:
            data.setdefault(p, stamp)
        _write(data)


def clear(paths: Iterable[str]) -> None:
    """Drop tombstones for ``paths`` (the file reappeared, or it was purged)."""
    paths = set(paths)
    if not paths:
        return
    with store_lock():
        data = dict(load())
        remaining = {p: t for p, t in data.items() if p not in paths}
        if remaining != data:
            _write(remaining)


def expired(grace: "float | None" = None, now: "float | None" = None) -> list[str]:
    """Tombstones older than the grace window (due for purging)."""
    g = grace_secs() if grace is None else grace
    t = time.time() if now is None else now
    return sorted(p for p, ts in load().items() if t - ts >= g)
