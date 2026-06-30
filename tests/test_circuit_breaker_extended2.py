# pylint: disable=missing-docstring, import-outside-toplevel, broad-exception-caught
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""tests/test_circuit_breaker_extended2.py — Coverage for memory/circuit_breaker.py (68% → 90%)."""
from __future__ import annotations

import time
from unittest.mock import patch, MagicMock

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_breaker(always_ok=True, rss_mb=100.0):
    from memory.circuit_breaker import CircuitBreaker
    from core.probes import RSSProbe, StorageSizeProbe
    if always_ok:
        from core.probes import ProbeResult
        ok_probe = MagicMock(return_value=ProbeResult(ok=True, reason=""))
        return CircuitBreaker(probes=[ok_probe])
    return CircuitBreaker(rss_limit_mb=rss_mb)


# ── basic state ───────────────────────────────────────────────────────────────

def test_initial_state_closed():
    cb = _make_breaker()
    from memory.circuit_breaker import State
    assert cb.state == State.CLOSED


def test_check_closed_passes():
    cb = _make_breaker(always_ok=True)
    cb.check()  # must not raise


def test_record_success_stays_closed():
    from memory.circuit_breaker import State
    cb = _make_breaker(always_ok=True)
    cb.record_success()
    assert cb.state == State.CLOSED


def test_reset_closes_breaker():
    from memory.circuit_breaker import State, CircuitBreaker
    from core.probes import ProbeResult
    fail_probe = MagicMock(return_value=ProbeResult(ok=False, reason="too much ram"))
    cb = CircuitBreaker(probes=[fail_probe])
    try:
        cb.check()
    except Exception:
        pass
    cb.reset()
    assert cb.state == State.CLOSED


# ── tripping open ─────────────────────────────────────────────────────────────

def test_check_trips_open_on_probe_failure():
    from memory.circuit_breaker import CircuitBreaker, CircuitOpenError, State
    from core.probes import ProbeResult
    fail_probe = MagicMock(return_value=ProbeResult(ok=False, reason="ram pressure"))
    cb = CircuitBreaker(probes=[fail_probe], cooldown_sec=300)
    with pytest.raises(CircuitOpenError):
        cb.check()
    assert cb.state == State.OPEN


def test_record_failure_trips_open():
    from memory.circuit_breaker import State
    cb = _make_breaker(always_ok=True)
    cb.record_failure()
    assert cb.state == State.OPEN


def test_check_open_raises_before_cooldown():
    from memory.circuit_breaker import CircuitBreaker, CircuitOpenError, State
    from core.probes import ProbeResult
    fail_probe = MagicMock(return_value=ProbeResult(ok=False, reason="oom"))
    cb = CircuitBreaker(probes=[fail_probe], cooldown_sec=300)
    try:
        cb.check()
    except CircuitOpenError:
        pass
    with pytest.raises(CircuitOpenError):
        cb.check()


# ── half-open transition ──────────────────────────────────────────────────────

def test_open_transitions_to_half_open_after_cooldown():
    from memory.circuit_breaker import CircuitBreaker, CircuitOpenError, State
    from core.probes import ProbeResult
    fail_probe = MagicMock(return_value=ProbeResult(ok=False, reason="oom"))
    ok_probe = MagicMock(return_value=ProbeResult(ok=True, reason=""))
    cb = CircuitBreaker(probes=[fail_probe], cooldown_sec=0.01)
    try:
        cb.check()
    except CircuitOpenError:
        pass
    # Replace probe with ok one
    cb._probes = [ok_probe]
    time.sleep(0.02)
    cb.check()  # Should allow through (half-open → passes)


def test_half_open_re_trips_on_probe_failure():
    from memory.circuit_breaker import CircuitBreaker, CircuitOpenError, State
    from core.probes import ProbeResult
    fail_probe = MagicMock(return_value=ProbeResult(ok=False, reason="oom"))
    cb = CircuitBreaker(probes=[fail_probe], cooldown_sec=0.01)
    try:
        cb.check()
    except CircuitOpenError:
        pass
    time.sleep(0.02)
    # First check after cooldown: OPEN → HALF_OPEN (returns without raising)
    cb.check()
    assert cb.state == State.HALF_OPEN
    # Second check in HALF_OPEN with still-failing probe re-trips to OPEN
    with pytest.raises(CircuitOpenError):
        cb.check()


# ── guard decorator ───────────────────────────────────────────────────────────

def test_guard_decorator_closed():
    cb = _make_breaker(always_ok=True)

    @cb.guard
    def my_fn():
        return 42

    result = my_fn()
    assert result == 42


def test_guard_decorator_open_returns_none():
    from memory.circuit_breaker import CircuitBreaker
    from core.probes import ProbeResult
    fail_probe = MagicMock(return_value=ProbeResult(ok=False, reason="oom"))
    cb = CircuitBreaker(probes=[fail_probe], cooldown_sec=300)

    @cb.guard
    def my_fn():
        return 42

    result = my_fn()
    assert result is None


# ── _rss_mb, _total_ram_mb ────────────────────────────────────────────────────

def test_rss_mb_returns_float():
    from memory.circuit_breaker import _rss_mb
    result = _rss_mb()
    assert isinstance(result, float)
    assert result >= 0


def test_total_ram_mb_returns_positive():
    from memory.circuit_breaker import _total_ram_mb
    result = _total_ram_mb()
    assert result > 0


# ── probes list ───────────────────────────────────────────────────────────────

def test_probes_property():
    cb = _make_breaker(always_ok=True)
    probes = cb.probes
    assert isinstance(probes, list)


# ── get_breaker singleton ─────────────────────────────────────────────────────

def test_get_breaker_returns_instance():
    from memory.circuit_breaker import get_breaker, CircuitBreaker
    cb = get_breaker()
    assert isinstance(cb, CircuitBreaker)


def test_get_breaker_singleton():
    from memory.circuit_breaker import get_breaker
    cb1 = get_breaker()
    cb2 = get_breaker()
    assert cb1 is cb2
