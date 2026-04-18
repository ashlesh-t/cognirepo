# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
server/idle_manager.py — TTL-based resource eviction for the MCP server.

After `idle_ttl_seconds` of inactivity (no MCP tool calls), registered
evict callbacks are fired to release heavy in-process resources:
  - SentenceTransformer embedding model (~400 MB)
  - KnowledgeGraph object
  - ASTIndexer object

Resources are reloaded lazily on the next tool call, so callers never
see a crash — only a ~2 s warm-up latency on the first post-idle request.

Usage
-----
    from server.idle_manager import get_idle_manager
    mgr = get_idle_manager()          # singleton, auto-started
    mgr.touch()                       # call on every tool invocation
    mgr.register_evict(my_evict_fn)   # register before first touch()
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

# Sentinel so tests can inject a custom TTL before the singleton is created.
_DEFAULT_TTL: int = 600  # 10 minutes


def _load_ttl_from_config() -> int:
    """Read idle_ttl_seconds from .cognirepo/config.json, falling back to default."""
    try:
        import json  # pylint: disable=import-outside-toplevel
        from config.paths import get_path  # pylint: disable=import-outside-toplevel
        path = get_path("config.json")
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
        return int(cfg.get("idle_ttl_seconds", _DEFAULT_TTL))
    except Exception:  # pylint: disable=broad-except
        return _DEFAULT_TTL


class IdleManager:
    """
    Background daemon that evicts heavy resources after a configurable idle TTL.

    Thread-safe.  The background thread wakes every `_check_interval` seconds
    (≥ 30 s, ≤ ttl/10) and fires evict callbacks when the idle time exceeds
    the TTL.  The timer is reset on every `touch()` call.
    """

    def __init__(self, ttl_seconds: int | None = None):
        self._ttl: int = ttl_seconds if ttl_seconds is not None else _load_ttl_from_config()
        self._last_active: float = time.monotonic()
        self._lock = threading.Lock()
        self._evict_callbacks: list[Callable[[], None]] = []
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._evicted = False  # True while resources are evicted

    # ── public API ────────────────────────────────────────────────────────────

    @property
    def ttl(self) -> int:
        return self._ttl

    def register_evict(self, fn: Callable[[], None]) -> None:
        """Register a zero-argument callable that releases a heavy resource."""
        self._evict_callbacks.append(fn)

    def touch(self) -> None:
        """Record activity.  Resets the idle timer."""
        with self._lock:
            self._last_active = time.monotonic()
            self._evicted = False

    def idle_seconds(self) -> float:
        """Return how many seconds have elapsed since the last touch()."""
        with self._lock:
            return time.monotonic() - self._last_active

    def is_evicted(self) -> bool:
        """True if resources have been evicted and not yet reloaded."""
        with self._lock:
            return self._evicted

    def start(self) -> None:
        """Start the background watcher thread (idempotent)."""
        if self._thread is not None:
            return
        self._stop_event.clear()
        check_interval = max(30, self._ttl // 10)
        self._thread = threading.Thread(
            target=self._run,
            args=(check_interval,),
            name="cognirepo-idle-manager",
            daemon=True,
        )
        self._thread.start()
        logger.debug("idle: manager started (ttl=%ds, check=%ds)", self._ttl, check_interval)

    def stop(self) -> None:
        """Stop the background thread.  Blocks up to 5 s."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def force_evict(self) -> None:
        """Evict immediately regardless of idle time (useful in tests)."""
        self._evict()

    # ── internal ──────────────────────────────────────────────────────────────

    def _run(self, check_interval: int) -> None:
        while not self._stop_event.wait(check_interval):
            if self.idle_seconds() >= self._ttl:
                self._evict()

    def _evict(self) -> None:
        logger.info(
            "idle: TTL %ds exceeded — evicting heavy resources (embedding model, graph, indexer)",
            self._ttl,
        )
        for fn in self._evict_callbacks:
            try:
                fn()
            except Exception:  # pylint: disable=broad-except
                logger.exception("idle: evict callback %r raised", fn)
        with self._lock:
            self._evicted = True
            # Reset so we don't fire again until the next idle period.
            self._last_active = time.monotonic()


# ── module-level singleton ────────────────────────────────────────────────────

_MANAGER: IdleManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_idle_manager(ttl_seconds: int | None = None) -> IdleManager:
    """
    Return the process-wide IdleManager singleton, creating and starting it
    on the first call.

    Pass `ttl_seconds` only on the first call (or in tests) — subsequent calls
    ignore the argument and return the already-running instance.
    """
    global _MANAGER  # pylint: disable=global-statement
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = IdleManager(ttl_seconds)
            _MANAGER.start()
        return _MANAGER


def reset_idle_manager() -> None:
    """Stop and discard the singleton.  Intended for tests only."""
    global _MANAGER  # pylint: disable=global-statement
    with _MANAGER_LOCK:
        if _MANAGER is not None:
            _MANAGER.stop()
            _MANAGER = None
