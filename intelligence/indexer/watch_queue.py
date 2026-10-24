# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""The bounded, coalescing FIFO between the file watcher's event thread and its single indexing consumer (#117).

Why it exists: the watcher used to keep an unbounded ``dict`` of pending paths and arm a fresh ``threading.Timer``
(a new OS thread) for every event, then index the whole dict as one batch — so a ``git checkout`` that touches tens
of thousands of files grew without bound, spawned a thread per event and held the flush lock for one giant batch.

Properties (all covered by ``tests/test_watch_queue.py``):

* **Coalescing.** One entry per path; the last action wins (a create followed by a delete is a delete). Re-touching a
  queued path does not move it, so ordering is by *first* arrival and nothing starves.
* **Bounded.** At most ``maxsize`` distinct paths. The event thread never blocks (watchdog would drop OS events): a
  new path that does not fit is *not* queued, ``overflowed`` is set and ``dropped`` counted. The consumer reacts by
  running a catch-up scan once the queue drains, so the index converges on the filesystem — an overflow costs a
  scan, never a missed edit.
* **Batched.** ``take_batch(n)`` hands the consumer at most ``n`` paths in FIFO order.

Thread-safe: every method takes the queue's own lock. No threads are created here.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

DEFAULT_MAXSIZE = 5000
DEFAULT_BATCH_MAX = 500
DEFAULT_MAX_LATENCY_MS = 5000


class WatchQueue:
    def __init__(self, maxsize: int = DEFAULT_MAXSIZE) -> None:
        self.maxsize = max(1, int(maxsize))
        self._items: "OrderedDict[str, tuple[str, float]]" = OrderedDict()   # path -> (action, first seen)
        self._lock = threading.Lock()
        self.overflowed = False
        self.stats: dict[str, Any] = {"enqueued": 0, "coalesced": 0, "dropped": 0, "overflows": 0,
                                      "batches": 0, "files": 0, "max_depth": 0, "last_batch": None}

    # -- producer side ------------------------------------------------------------------------
    def put(self, action: str, path: str) -> str:
        """Queue ``path``. Returns ``"queued"``, ``"coalesced"`` (already queued, action updated) or
        ``"overflow"`` (full and ``path`` is new: not queued)."""
        with self._lock:
            held = self._items.get(path)
            if held is not None:
                self._items[path] = (action, held[1])           # same position, newest action
                self.stats["coalesced"] += 1
                return "coalesced"
            if len(self._items) >= self.maxsize:
                if not self.overflowed:
                    self.stats["overflows"] += 1
                self.overflowed = True
                self.stats["dropped"] += 1
                return "overflow"
            self._items[path] = (action, time.monotonic())
            self.stats["enqueued"] += 1
            if len(self._items) > self.stats["max_depth"]:
                self.stats["max_depth"] = len(self._items)
            return "queued"

    # -- consumer side ------------------------------------------------------------------------
    def take_batch(self, n: int) -> list[tuple[str, str]]:
        """Remove and return up to ``n`` ``(path, action)`` pairs, oldest first."""
        with self._lock:
            out: list[tuple[str, str]] = []
            while self._items and len(out) < max(1, n):
                path, (action, _) = self._items.popitem(last=False)
                out.append((path, action))
            return out

    def take_overflow(self) -> bool:
        """True once per overflow episode (and resets it): the consumer must reconcile with a catch-up scan."""
        with self._lock:
            was, self.overflowed = self.overflowed, False
            return was

    def record_batch(self, files: int, ms: float) -> None:
        with self._lock:
            self.stats["batches"] += 1
            self.stats["files"] += files
            self.stats["last_batch"] = {"files": files, "ms": round(ms, 1)}

    def replace(self, items: dict[str, str]) -> None:
        """Replace the whole contents (kept for code that assigns a pending dict directly). Not bounded."""
        with self._lock:
            now = time.monotonic()
            self._items = OrderedDict((p, (a, now)) for p, a in items.items())

    # -- introspection ------------------------------------------------------------------------
    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return {p: a for p, (a, _) in self._items.items()}

    def oldest_age(self) -> float:
        """Seconds the oldest queued path has waited (0 when empty)."""
        with self._lock:
            if not self._items:
                return 0.0
            return time.monotonic() - next(iter(self._items.values()))[1]

    def describe(self) -> dict[str, Any]:
        with self._lock:
            return {"depth": len(self._items), "max": self.maxsize,
                    "oldest_age_s": round(time.monotonic() - next(iter(self._items.values()))[1], 2)
                    if self._items else 0.0,
                    **{k: (dict(v) if isinstance(v, dict) else v) for k, v in self.stats.items()}}


STATUS_FILE = "watch_queue.json"


def read_status(store_dir: str) -> dict[str, Any] | None:
    """The watcher's last-published queue state from ``<store>/index/watch_queue.json``, or ``None`` if there is none
    or the watcher that wrote it is gone (a dead process's depth would only mislead). Read-only."""
    import json
    import os
    try:
        with open(os.path.join(store_dir, "index", STATUS_FILE), encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    pid = doc.get("pid")
    if isinstance(pid, int):
        from core.config import procutil
        if not procutil.pid_alive(pid):
            return None
    return doc
