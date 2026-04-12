# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Circuit Breaker — prevents OOM by monitoring RSS memory usage before
any allocation-heavy operation (FAISS add, embedding encode, graph build).

States
------
CLOSED   — normal operation; all calls go through
OPEN     — memory pressure detected; calls are blocked and raise CircuitOpenError
HALF_OPEN— a probe call is allowed to test whether pressure has lifted

Thresholds (configurable via .cognirepo/config.json or environment)
-----------
COGNIREPO_CB_RSS_LIMIT_MB   — RSS limit in MB (default: 80 % of total system RAM)
COGNIREPO_CB_COOLDOWN_SEC   — seconds to wait in OPEN before retrying (default: 30)

Usage
-----
    from memory.circuit_breaker import get_breaker, CircuitOpenError

    breaker = get_breaker()
    try:
        breaker.check()          # raises if OPEN
        # ... heavy memory op ...
        breaker.record_success()
    except CircuitOpenError:
        # shed load — return cached result or empty list
        return []

    # Or use the decorator:
    @breaker.guard
    def heavy_fn(): ...
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from enum import Enum
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

_F = TypeVar("_F", bound=Callable)

# ── state machine ─────────────────────────────────────────────────────────────

class State(str, Enum):
    """Possible states for the CircuitBreaker."""
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(RuntimeError):
    """Raised when the circuit breaker is OPEN (memory pressure too high)."""


# ── helpers ───────────────────────────────────────────────────────────────────

def _total_ram_mb() -> float:
    """Return total system RAM in MB without psutil dependency."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 1024  # kB → MB
    except OSError:
        pass
    return 4096.0  # safe fallback: assume 4 GB


def _rss_mb() -> float:
    """Return current process RSS in MB (reads /proc/self/status — no psutil)."""
    try:
        with open("/proc/self/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024  # kB → MB
    except OSError:
        pass
    return 0.0


def _default_limit_mb() -> float:
    env_val = os.environ.get("COGNIREPO_CB_RSS_LIMIT_MB", "")
    if env_val:
        try:
            return float(env_val)
        except ValueError:
            pass
    # Try config.json
    try:
        from config.paths import get_path
        with open(get_path("config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        limit = cfg.get("circuit_breaker", {}).get("rss_limit_mb")
        if limit:
            return float(limit)
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    return _total_ram_mb() * 0.80  # 80 % of total RAM


def _cooldown_sec() -> float:
    env_val = os.environ.get("COGNIREPO_CB_COOLDOWN_SEC", "")
    if env_val:
        try:
            return float(env_val)
        except ValueError:
            pass
    return 30.0


# ── circuit breaker ───────────────────────────────────────────────────────────

class CircuitBreaker:
    """
    Thread-safe circuit breaker backed by a list of pluggable probes.

    Backward compatible: pass `rss_limit_mb` and the breaker behaves
    exactly as before (only the RSS probe is used).  Pass `probes` to
    override the probe list entirely.
    """

    def __init__(
        self,
        rss_limit_mb: float | None = None,
        cooldown_sec: float | None = None,
        name: str = "default",
        probes: list | None = None,
    ) -> None:
        self._name = name
        self._cooldown = cooldown_sec if cooldown_sec is not None else _cooldown_sec()
        self._state: State = State.CLOSED
        self._opened_at: float = 0.0
        self._lock = threading.Lock()
        self._last_fail_reason: str = ""

        if probes is not None:
            self._probes = probes
        else:
            from cron.probes import RSSProbe, StorageSizeProbe  # pylint: disable=import-outside-toplevel
            limit = rss_limit_mb if rss_limit_mb is not None else _default_limit_mb()
            self._probes = [RSSProbe(limit), StorageSizeProbe()]

    # ── public interface ──────────────────────────────────────────────────────

    @property
    def state(self) -> State:
        """Return the current circuit state (CLOSED, OPEN, HALF_OPEN)."""
        return self._state

    @property
    def probes(self) -> list:
        """Return the list of configured probes (read-only view)."""
        return list(self._probes)

    def _run_probes(self) -> tuple[bool, str]:
        """Run all probes; return (all_ok, first_failure_reason)."""
        for probe in self._probes:
            try:
                result = probe()
                if not result.ok:
                    return False, result.reason
            except Exception as exc:  # pylint: disable=broad-except
                return False, f"probe error: {exc}"
        return True, ""

    def check(self) -> None:
        """
        Check whether the circuit allows the call through.
        Raises CircuitOpenError if any probe fails.
        Transitions OPEN→HALF_OPEN when cooldown elapses.
        """
        with self._lock:
            if self._state == State.CLOSED:
                ok, reason = self._run_probes()
                if not ok:
                    self._trip(reason)
                    raise CircuitOpenError(
                        f"[CircuitBreaker:{self._name}] {reason} — shedding load"
                    )
                return

            if self._state == State.OPEN:
                elapsed = time.monotonic() - self._opened_at
                if elapsed < self._cooldown:
                    raise CircuitOpenError(
                        f"[CircuitBreaker:{self._name}] OPEN — retry in "
                        f"{self._cooldown - elapsed:.0f}s"
                    )
                # Cooldown elapsed — allow one probe call
                self._state = State.HALF_OPEN
                logger.info("[CB:%s] HALF_OPEN probe", self._name)
                return

            # HALF_OPEN — allow the call; record_success/record_failure closes or re-opens
            ok, reason = self._run_probes()
            if not ok:
                self._trip(reason)
                raise CircuitOpenError(
                    f"[CircuitBreaker:{self._name}] HALF_OPEN probe failed — {reason}"
                )

    def record_success(self) -> None:
        """Inform the breaker that a call succeeded; closes the circuit."""
        with self._lock:
            if self._state != State.CLOSED:
                logger.info("[CB:%s] → CLOSED", self._name)
            self._state = State.CLOSED
            self._update_metric()

    def record_failure(self) -> None:
        """Inform the breaker that a call failed; trips the circuit OPEN."""
        with self._lock:
            self._trip("record_failure() called")

    def reset(self) -> None:
        """Force CLOSED — for use in tests or after manual GC."""
        with self._lock:
            self._state = State.CLOSED
            self._opened_at = 0.0

    # ── decorator ─────────────────────────────────────────────────────────────

    def guard(self, fn: _F) -> _F:
        """
        Decorator: wraps a function with circuit-breaker check.
        On CircuitOpenError the function returns None (not re-raised).
        """
        import functools  # pylint: disable=import-outside-toplevel

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                self.check()
            except CircuitOpenError as exc:
                logger.warning("%s", exc)
                return None
            result = fn(*args, **kwargs)
            self.record_success()
            return result

        return wrapper  # type: ignore[return-value]

    # ── internal ──────────────────────────────────────────────────────────────

    def _trip(self, reason: str) -> None:
        self._state = State.OPEN
        self._opened_at = time.monotonic()
        self._last_fail_reason = reason
        logger.warning(
            "[CB:%s] OPEN — %s — will retry in %.0fs",
            self._name, reason, self._cooldown,
        )
        self._update_metric()

    def _update_metric(self) -> None:
        """Update the Prometheus CB_STATE gauge (no-op if prometheus not installed)."""
        try:
            from api.metrics import CB_STATE  # pylint: disable=import-outside-toplevel
            _state_value = {"CLOSED": 0, "HALF_OPEN": 1, "OPEN": 2}
            CB_STATE.set(_state_value.get(self._state.value, 0))
        except Exception:  # pylint: disable=broad-except
            pass


# ── module-level singleton ────────────────────────────────────────────────────

_BREAKER: CircuitBreaker | None = None
_BREAKER_LOCK = threading.Lock()


def get_breaker(name: str = "cognirepo") -> CircuitBreaker:
    """Return the shared CircuitBreaker instance (created once)."""
    global _BREAKER  # pylint: disable=global-statement
    with _BREAKER_LOCK:
        if _BREAKER is None:
            _BREAKER = CircuitBreaker(name=name)
    return _BREAKER
