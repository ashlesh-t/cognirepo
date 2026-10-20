# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Cheap, read-only size accounting for a ``.cognirepo/`` store (#212).

Used by ``GET /api/v1/status`` (``indexer.store_bytes``) and the ``/metrics`` collector. Walking the
store is not free on a big vector directory, so results are cached for a short TTL per store.
"""
from __future__ import annotations

import os
import threading
import time

TTL_SECS = 30.0
_cache: dict[str, tuple[float, dict[str, int]]] = {}
_lock = threading.Lock()


def dir_bytes(path: str) -> int:
    """Total size of regular files under ``path`` (symlinks are not followed). 0 if it does not exist."""
    total = 0
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def store_sizes(store: str, ttl: float = TTL_SECS) -> dict[str, int]:
    """``{<top-level directory>: bytes, "_files": bytes, "total": bytes}`` for a store; cached ``ttl`` seconds.
    ``_files`` is every loose file at the top level (config, lock, ...) summed."""
    now = time.monotonic()
    with _lock:
        hit = _cache.get(store)
        if hit and now - hit[0] < ttl:
            return dict(hit[1])
    sizes: dict[str, int] = {}
    try:
        with os.scandir(store) as it:
            for entry in it:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        sizes[entry.name] = dir_bytes(entry.path)
                    elif entry.is_file(follow_symlinks=False):    # loose files are summed, not listed
                        sizes["_files"] = sizes.get("_files", 0) + entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
    except OSError:
        pass
    sizes["total"] = sum(sizes.values())
    with _lock:
        _cache[store] = (now, sizes)
    return dict(sizes)
