# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Tests for cron/scheduler.py — BackgroundScheduler."""
import threading
import time

from cron.scheduler import BackgroundScheduler


def test_scheduler_fires_task():
    """The scheduled task must execute within the interval."""
    fired = threading.Event()

    def _task():
        fired.set()

    scheduler = BackgroundScheduler(fn=_task, interval_sec=0.05, name="test-fire")
    scheduler.start()
    result = fired.wait(timeout=3.0)
    scheduler.stop()
    assert result, "Task did not fire within 3s"


def test_scheduler_stop_prevents_future_runs():
    """After stop(), no more task runs should occur."""
    run_count = [0]
    lock = threading.Lock()

    def _task():
        with lock:
            run_count[0] += 1

    scheduler = BackgroundScheduler(fn=_task, interval_sec=0.05, name="test-stop")
    scheduler.start()
    time.sleep(0.12)   # let it fire at least once
    scheduler.stop()
    count_at_stop = run_count[0]
    time.sleep(0.15)   # wait for a cycle that should NOT fire
    assert run_count[0] == count_at_stop, "Task ran after stop()"


def test_scheduler_skips_when_breaker_open(monkeypatch):
    """When the circuit breaker is OPEN the scheduled task must be skipped."""
    from cron.probes import ProbeResult
    from memory.circuit_breaker import get_breaker, CircuitBreaker

    # Replace the singleton with a tripped breaker
    bad_breaker = CircuitBreaker(
        probes=[lambda: ProbeResult(ok=False, reason="test")],
        cooldown_sec=60,
        name="test-tripped",
    )
    # Trip it
    try:
        bad_breaker.check()
    except Exception:
        pass

    monkeypatch.setattr("memory.circuit_breaker._BREAKER", bad_breaker)

    task_ran = [False]

    def _task():
        task_ran[0] = True

    scheduler = BackgroundScheduler(fn=_task, interval_sec=0.05, name="test-skip")
    scheduler.start()
    time.sleep(0.25)   # give it time to (not) run
    scheduler.stop()

    assert not task_ran[0], "Task should have been skipped due to open circuit"


def test_scheduler_next_run_advances():
    """next_run_timestamp must increase after each run."""
    event = threading.Event()

    def _task():
        event.set()

    scheduler = BackgroundScheduler(fn=_task, interval_sec=0.05, name="test-advance")
    scheduler.start()
    t_before = scheduler.next_run_timestamp()
    event.wait(timeout=2.0)
    time.sleep(0.01)  # let the reschedule happen
    t_after = scheduler.next_run_timestamp()
    scheduler.stop()
    assert t_after > t_before, "next_run_timestamp did not advance"
