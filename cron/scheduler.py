# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Lightweight background scheduler — stdlib threading.Timer only.

Invoked on startup when
``config.json → prune.auto_enabled = true``.

Reads the schedule from:
  1. .cognirepo/prune_schedule.json → every_hours (int)
  2. config.json → prune.every_hours (int)
  3. Default: 24 h

The scheduler refuses to run a prune if the circuit breaker is OPEN.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

_DEFAULT_EVERY_HOURS = 24
_SCHEDULE_FILE_NAME = "prune_schedule.json"


def _schedule_interval_hours() -> int:
    """Resolve interval_hours from schedule JSON or config.json."""
    try:
        from config.paths import get_path  # pylint: disable=import-outside-toplevel
        sched_path = get_path(_SCHEDULE_FILE_NAME)
        if os.path.exists(sched_path):
            with open(sched_path, encoding="utf-8") as f:
                data = json.load(f)
            hours = int(data.get("every_hours", _DEFAULT_EVERY_HOURS))
            if hours > 0:
                return hours
    except Exception:  # pylint: disable=broad-except
        pass

    try:
        from config.paths import get_path  # pylint: disable=import-outside-toplevel
        with open(get_path("config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        hours = int(cfg.get("prune", {}).get("every_hours", _DEFAULT_EVERY_HOURS))
        if hours > 0:
            return hours
    except Exception:  # pylint: disable=broad-except
        pass

    return _DEFAULT_EVERY_HOURS


def _auto_prune_enabled() -> bool:
    try:
        from config.paths import get_path  # pylint: disable=import-outside-toplevel
        with open(get_path("config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        return bool(cfg.get("prune", {}).get("auto_enabled", False))
    except Exception:  # pylint: disable=broad-except
        return False


class BackgroundScheduler:
    """
    Runs a callable on a fixed-interval background thread.

    Example:
        scheduler = BackgroundScheduler(
            fn=run_prune,
            interval_sec=86400,
            name="auto-prune",
        )
        scheduler.start()
        # ... later:
        scheduler.stop()
    """

    def __init__(
        self,
        fn: Callable[[], None],
        interval_sec: float,
        name: str = "scheduler",
    ) -> None:
        self._fn = fn
        self._interval = interval_sec
        self._name = name
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._stopped = False
        self._next_run: float = 0.0

    def start(self) -> None:
        """Schedule the first run after one interval."""
        with self._lock:
            if self._stopped:
                return
            self._next_run = time.monotonic() + self._interval
            self._schedule_next()
        logger.info(
            "[Scheduler:%s] started — interval %.1f h",
            self._name, self._interval / 3600,
        )

    def stop(self) -> None:
        """Cancel any pending timer and stop scheduling."""
        with self._lock:
            self._stopped = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        logger.info("[Scheduler:%s] stopped", self._name)

    def next_run_timestamp(self) -> float:
        """Return monotonic timestamp of the next scheduled run."""
        return self._next_run

    def _schedule_next(self) -> None:
        delay = max(0.0, self._next_run - time.monotonic())
        self._timer = threading.Timer(delay, self._run)
        self._timer.daemon = True
        self._timer.start()

    def _run(self) -> None:
        if self._stopped:
            return
        # Check circuit breaker
        try:
            from memory.circuit_breaker import get_breaker  # pylint: disable=import-outside-toplevel
            breaker = get_breaker()
            breaker.check()
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("[Scheduler:%s] skipping run — breaker: %s", self._name, exc)
            self._advance_and_reschedule()
            return

        try:
            logger.info("[Scheduler:%s] running scheduled task", self._name)
            self._fn()
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("[Scheduler:%s] task raised: %s", self._name, exc)

        self._advance_and_reschedule()

    def _advance_and_reschedule(self) -> None:
        with self._lock:
            if self._stopped:
                return
            self._next_run = time.monotonic() + self._interval
            self._schedule_next()


# ── module-level auto-prune scheduler ────────────────────────────────────────

_AUTO_PRUNE_SCHEDULER: BackgroundScheduler | None = None
_CLEANUP_SCHEDULER: BackgroundScheduler | None = None


def _run_auto_prune() -> None:
    """Thin wrapper that calls the prune function."""
    from cron.prune_memory import prune  # pylint: disable=import-outside-toplevel
    result = prune(verbose=False)
    logger.info("[auto-prune] result: %s", result)


def _run_cleanup_suppressed() -> None:
    """Thin wrapper that drains the suppression cleanup queue."""
    from cron.prune_memory import cleanup_suppressed  # pylint: disable=import-outside-toplevel
    result = cleanup_suppressed()
    logger.info("[cleanup-suppressed] result: %s", result)


def start_auto_prune_scheduler() -> BackgroundScheduler | None:
    """
    Start the auto-prune and suppression-cleanup background schedulers if
    config enables them.  Returns the prune scheduler, or None if disabled.
    """
    global _AUTO_PRUNE_SCHEDULER, _CLEANUP_SCHEDULER  # pylint: disable=global-statement

    if _AUTO_PRUNE_SCHEDULER is not None:
        return _AUTO_PRUNE_SCHEDULER  # already running

    if not _auto_prune_enabled():
        logger.debug("[Scheduler] auto_prune not enabled in config — skipping")
        return None

    hours = _schedule_interval_hours()
    interval_sec = hours * 3600

    scheduler = BackgroundScheduler(
        fn=_run_auto_prune,
        interval_sec=interval_sec,
        name="auto-prune",
    )
    scheduler.start()
    _AUTO_PRUNE_SCHEDULER = scheduler

    # Cleanup suppressed entries runs on the same interval as auto-prune
    if _CLEANUP_SCHEDULER is None:
        cleanup_sched = BackgroundScheduler(
            fn=_run_cleanup_suppressed,
            interval_sec=interval_sec,
            name="cleanup-suppressed",
        )
        cleanup_sched.start()
        _CLEANUP_SCHEDULER = cleanup_sched
        logger.info("[Scheduler] cleanup-suppressed started, interval=%sh", hours)

    return scheduler


def write_prune_schedule(every_hours: int) -> str:
    """
    Write .cognirepo/prune_schedule.json with the given interval.
    Returns the path written.
    """
    from config.paths import get_path  # pylint: disable=import-outside-toplevel
    path = get_path(_SCHEDULE_FILE_NAME)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"every_hours": every_hours}, f)
    logger.info("Wrote prune schedule: every %d h → %s", every_hours, path)
    return path
