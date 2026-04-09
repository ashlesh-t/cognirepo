# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
In-process token-bucket rate limiter.

One bucket per client_id (JWT sub or client IP). Buckets are refilled
continuously at `per_minute` tokens/minute and capped at `burst` tokens.

Config (in order of precedence):
  1. Environment variables:
       COGNIREPO_RATE_LIMIT_PER_MINUTE  (float, default 60)
       COGNIREPO_RATE_LIMIT_BURST       (float, default 20)
       COGNIREPO_RATE_LIMIT_ENABLED     (true/false, default true)
  2. .cognirepo/config.json → rate_limit.{per_minute,burst,enabled}
  3. Built-in defaults

Note: bucket state is in-process — it does not survive restarts.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

# ── default config ─────────────────────────────────────────────────────────────

_DEFAULT_PER_MINUTE = 60.0
_DEFAULT_BURST = 20.0


def _load_config() -> dict:
    try:
        from config.paths import get_path  # pylint: disable=import-outside-toplevel
        with open(get_path("config.json"), encoding="utf-8") as f:
            return json.load(f).get("rate_limit", {})
    except Exception:  # pylint: disable=broad-except
        return {}


def _enabled() -> bool:
    env = os.environ.get("COGNIREPO_RATE_LIMIT_ENABLED", "").lower()
    if env in ("false", "0", "no"):
        return False
    if env in ("true", "1", "yes"):
        return True
    cfg = _load_config()
    return cfg.get("enabled", True)


def _per_minute() -> float:
    env = os.environ.get("COGNIREPO_RATE_LIMIT_PER_MINUTE", "")
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    return float(_load_config().get("per_minute", _DEFAULT_PER_MINUTE))


def _burst() -> float:
    env = os.environ.get("COGNIREPO_RATE_LIMIT_BURST", "")
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    return float(_load_config().get("burst", _DEFAULT_BURST))


# ── token bucket ───────────────────────────────────────────────────────────────

class _Bucket:
    """Token bucket for a single client."""

    __slots__ = ("_tokens", "_last_refill", "_lock")

    def __init__(self, initial_tokens: float) -> None:
        self._tokens = initial_tokens
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def consume(self, per_minute: float, burst: float) -> tuple[bool, float]:
        """
        Attempt to consume 1 token.

        Returns (allowed: bool, retry_after: float).
        retry_after is 0.0 when allowed, seconds to wait otherwise.
        """
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            refill = elapsed * (per_minute / 60.0)
            self._tokens = min(burst, self._tokens + refill)
            self._last_refill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True, 0.0

            # Calculate how many seconds until 1 token is available
            deficit = 1.0 - self._tokens
            retry_after = deficit / (per_minute / 60.0)
            return False, retry_after


class RateLimiter:
    """
    Process-wide token-bucket rate limiter.

    Usage:
        limiter = RateLimiter()
        allowed, retry_after = await limiter.check(client_id)
    """

    def __init__(self) -> None:
        self._buckets: dict[str, _Bucket] = {}
        self._lock = asyncio.Lock()

    async def check(self, client_id: str) -> tuple[bool, float]:
        """
        Check and consume a token for client_id.

        Returns (allowed, retry_after_seconds).
        """
        if not _enabled():
            return True, 0.0

        per_min = _per_minute()
        burst = _burst()

        async with self._lock:
            if client_id not in self._buckets:
                self._buckets[client_id] = _Bucket(burst)
            bucket = self._buckets[client_id]

        return await bucket.consume(per_min, burst)

    def clear(self) -> None:
        """Reset all buckets (for testing)."""
        self._buckets.clear()


# ── module-level singleton ─────────────────────────────────────────────────────

_LIMITER: RateLimiter | None = None


def get_limiter() -> RateLimiter:
    """Return the process-wide rate limiter singleton."""
    global _LIMITER  # pylint: disable=global-statement
    if _LIMITER is None:
        _LIMITER = RateLimiter()
    return _LIMITER
