# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
server/memory_watchdog.py — degrade instead of being OOM-killed (#98).

The circuit breaker only looks at RSS at a few call sites (embed, graph save),
so a runaway anywhere else is invisible to it. This daemon samples RSS every
few seconds and, independent of what the process is doing:

  soft threshold (75 % of the limit) — run the registered evict callbacks
      (embedding model, graph, indexer) and gc.collect(), at most once per
      ``_SOFT_COOLDOWN_SEC``.
  hard threshold (the breaker's RSS limit) — additionally trip the shared
      circuit breaker so allocation-heavy calls shed load until RSS recovers.

It never kills the process. Every action is logged (to stderr via logging —
stdout is reserved for JSON-RPC) with the RSS reading for diagnosis.
"""
from __future__ import annotations

import gc
import logging
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

_SOFT_FRACTION = 0.75
_SOFT_COOLDOWN_SEC = 30.0


class MemoryWatchdog:
    """Background RSS sampler. See module docstring."""

    def __init__(
        self,
        limit_mb: float,
        evict_callbacks: list[Callable[[], None]] | None = None,
        interval_sec: float = 5.0,
        rss_reader: Callable[[], float] | None = None,
    ) -> None:
        if rss_reader is None:
            from data.memory.circuit_breaker import _rss_mb  # pylint: disable=import-outside-toplevel
            rss_reader = _rss_mb
        self._limit = limit_mb
        self._soft = limit_mb * _SOFT_FRACTION
        self._evict = list(evict_callbacks or [])
        self._interval = interval_sec
        self._rss = rss_reader
        self._last_soft = float("-inf")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the sampler thread (idempotent)."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="cognirepo-memory-watchdog", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the sampler thread."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def check_once(self) -> str:
        """Sample RSS once and act. Returns "ok", "soft" or "hard" (for tests)."""
        rss = self._rss()
        if rss < self._soft:
            return "ok"
        now = time.monotonic()
        hard = rss >= self._limit
        if now - self._last_soft >= _SOFT_COOLDOWN_SEC:
            self._last_soft = now
            logger.warning(
                "memory-watchdog: RSS %.0f MB >= soft threshold %.0f MB — "
                "evicting resources and collecting garbage", rss, self._soft,
            )
            for fn in self._evict:
                try:
                    fn()
                except Exception:  # pylint: disable=broad-except
                    logger.exception("memory-watchdog: evict callback %r raised", fn)
            gc.collect()
        if hard:
            from data.memory.circuit_breaker import get_breaker  # pylint: disable=import-outside-toplevel
            logger.error(
                "memory-watchdog: RSS %.0f MB >= limit %.0f MB — tripping circuit "
                "breaker; heavy operations will shed load", rss, self._limit,
            )
            get_breaker().record_failure()
            return "hard"
        return "soft"

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.check_once()
            except Exception:  # pylint: disable=broad-except
                logger.exception("memory-watchdog: sample failed")


def start_memory_watchdog(evict_callbacks: list[Callable[[], None]]) -> MemoryWatchdog:
    """Create and start a watchdog using the circuit breaker's RSS limit."""
    from data.memory.circuit_breaker import _default_limit_mb  # pylint: disable=import-outside-toplevel
    dog = MemoryWatchdog(_default_limit_mb(), evict_callbacks)
    dog.start()
    return dog
