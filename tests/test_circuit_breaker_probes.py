# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""Tests for generalized circuit breaker + cron/probes.py."""
import pytest

from cron.probes import ProbeResult, RSSProbe, DiskFreeProbe
from memory.circuit_breaker import CircuitBreaker, CircuitOpenError, State


# ── probe unit tests ──────────────────────────────────────────────────────────

def test_rss_probe_ok_when_under_limit():
    probe = RSSProbe(limit_mb=99999.0)
    result = probe()
    assert result.ok is True


def test_rss_probe_fails_when_over_limit():
    probe = RSSProbe(limit_mb=0.001)  # impossibly small — always fails
    result = probe()
    assert result.ok is False
    assert "RSS" in result.reason


def test_disk_free_probe_ok_on_existing_path(tmp_path):
    probe = DiskFreeProbe(min_free_mb=0.0, path=str(tmp_path))
    result = probe()
    assert result.ok is True


def test_disk_free_probe_fails_on_huge_minimum(tmp_path):
    probe = DiskFreeProbe(min_free_mb=999_999_999.0, path=str(tmp_path))
    result = probe()
    assert result.ok is False


def test_fake_probe_trips_breaker():
    """A custom probe returning ok=False must trip the circuit."""
    def always_fail() -> ProbeResult:
        return ProbeResult(ok=False, reason="test failure")

    cb = CircuitBreaker(probes=[always_fail], cooldown_sec=0.01, name="test1")
    assert cb.state == State.CLOSED

    with pytest.raises(CircuitOpenError):
        cb.check()

    assert cb.state == State.OPEN


def test_passing_probes_keep_circuit_closed():
    """All probes returning ok=True must keep the circuit closed."""
    def always_ok() -> ProbeResult:
        return ProbeResult(ok=True, reason="all good")

    cb = CircuitBreaker(probes=[always_ok], name="test2")
    cb.check()
    assert cb.state == State.CLOSED


def test_backward_compat_rss_only():
    """Default constructor (no probes arg) still uses RSSProbe with high limit."""
    cb = CircuitBreaker(rss_limit_mb=99999.0, name="compat")
    cb.check()  # must not raise
    assert cb.state == State.CLOSED


def test_multiple_probes_first_failure_trips():
    """First failing probe trips the breaker; subsequent probes are short-circuited."""
    calls = []

    def fail_probe() -> ProbeResult:
        calls.append("fail")
        return ProbeResult(ok=False, reason="first")

    def second_probe() -> ProbeResult:
        calls.append("second")
        return ProbeResult(ok=True)

    cb = CircuitBreaker(probes=[fail_probe, second_probe], cooldown_sec=0.01, name="multi")
    with pytest.raises(CircuitOpenError):
        cb.check()

    assert "fail" in calls
    # second probe must NOT have been called (short-circuit)
    assert "second" not in calls


def test_record_success_closes_circuit():
    def fail_probe() -> ProbeResult:
        return ProbeResult(ok=False, reason="oops")

    cb = CircuitBreaker(probes=[fail_probe], cooldown_sec=0.01, name="close")
    with pytest.raises(CircuitOpenError):
        cb.check()
    assert cb.state == State.OPEN

    cb.record_success()
    assert cb.state == State.CLOSED
