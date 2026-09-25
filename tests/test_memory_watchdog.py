# pylint: disable=missing-docstring, import-outside-toplevel, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""tests/test_memory_watchdog.py — #98: RSS guard degrades instead of OOM."""
from __future__ import annotations

from unittest import mock

from interface.server.memory_watchdog import MemoryWatchdog


def _dog(rss, evict=None, limit=1000.0):
    return MemoryWatchdog(limit, evict, rss_reader=lambda: rss[0])


def test_below_soft_threshold_does_nothing():
    evicted = []
    dog = _dog([100.0], [lambda: evicted.append(1)])
    assert dog.check_once() == "ok"
    assert evicted == []


def test_soft_threshold_evicts_and_is_rate_limited():
    evicted = []
    rss = [800.0]  # >= 750 soft, < 1000 limit
    dog = _dog(rss, [lambda: evicted.append(1)])
    assert dog.check_once() == "soft"
    assert dog.check_once() == "soft"
    assert evicted == [1]  # second sample inside the cooldown does not re-evict


def test_hard_threshold_trips_breaker():
    from data.memory.circuit_breaker import CircuitBreaker, CircuitOpenError, State
    breaker = CircuitBreaker(probes=[])
    dog = _dog([1200.0])
    with mock.patch("data.memory.circuit_breaker.get_breaker", return_value=breaker):
        assert dog.check_once() == "hard"
    assert breaker.state == State.OPEN
    try:
        breaker.check()
    except CircuitOpenError:
        pass
    else:
        raise AssertionError("breaker should shed load")


def test_failing_evict_callback_does_not_stop_the_guard():
    def boom():
        raise RuntimeError("x")
    ok = []
    dog = _dog([800.0], [boom, lambda: ok.append(1)])
    assert dog.check_once() == "soft"
    assert ok == [1]


def test_default_limit_is_capped(monkeypatch):
    from data.memory import circuit_breaker as cb
    monkeypatch.delenv("COGNIREPO_CB_RSS_LIMIT_MB", raising=False)
    monkeypatch.setattr(cb, "_total_ram_mb", lambda: 15000.0)
    assert cb._default_limit_mb() == cb._DEFAULT_RSS_CAP_MB
    monkeypatch.setattr(cb, "_total_ram_mb", lambda: 2000.0)
    assert cb._default_limit_mb() == 1600.0


def test_env_override_beats_cap(monkeypatch):
    from data.memory import circuit_breaker as cb
    monkeypatch.setenv("COGNIREPO_CB_RSS_LIMIT_MB", "8000")
    assert cb._default_limit_mb() == 8000.0
