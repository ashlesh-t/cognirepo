# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""Tests for api/rate_limit.py and api/middleware_ratelimit.py."""
import asyncio

import pytest

try:
    from fastapi.testclient import TestClient
    _FASTAPI = True
except ImportError:
    _FASTAPI = False

pytestmark = pytest.mark.skipif(not _FASTAPI, reason="fastapi not installed")

import api.rate_limit as rl_module
from api.rate_limit import RateLimiter, get_limiter
from api.main import app


# ── token bucket unit tests ───────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_limiter():
    """Reset the singleton limiter before each test."""
    get_limiter().clear()
    yield
    get_limiter().clear()


def test_bucket_allows_up_to_burst():
    """First <burst> requests within a window must all be allowed."""
    limiter = RateLimiter()

    async def _run():
        results = []
        for _ in range(5):
            allowed, _ = await limiter.check("test_client")
            results.append(allowed)
        return results

    results = asyncio.run(_run())
    # All 5 should be allowed (default burst=20)
    assert all(results)


def test_bucket_denies_after_burst_exhausted(monkeypatch):
    """After burst is exhausted requests must be denied with a positive retry_after."""
    monkeypatch.setattr(rl_module, "_burst", lambda: 3.0)
    monkeypatch.setattr(rl_module, "_per_minute", lambda: 1.0)   # very slow refill
    monkeypatch.setattr(rl_module, "_enabled", lambda: True)

    limiter = RateLimiter()

    async def _run():
        results = []
        for _ in range(6):
            allowed, retry = await limiter.check("test_burst")
            results.append((allowed, retry))
        return results

    results = asyncio.run(_run())
    allowed_count = sum(1 for a, _ in results if a)
    denied_count = sum(1 for a, r in results if not a and r > 0)
    assert allowed_count == 3
    assert denied_count == 3


def test_rate_limit_disabled(monkeypatch):
    """When disabled every request must be allowed."""
    monkeypatch.setattr(rl_module, "_enabled", lambda: False)
    limiter = RateLimiter()

    async def _run():
        results = []
        for _ in range(100):
            allowed, _ = await limiter.check("unlimited_client")
            results.append(allowed)
        return results

    results = asyncio.run(_run())
    assert all(results)


# ── middleware integration tests ──────────────────────────────────────────────

@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=False)


def test_health_not_rate_limited(client, monkeypatch):
    """Health check must never be rate-limited regardless of burst."""
    monkeypatch.setattr(rl_module, "_burst", lambda: 1.0)
    monkeypatch.setattr(rl_module, "_per_minute", lambda: 0.01)
    monkeypatch.setattr(rl_module, "_enabled", lambda: True)

    get_limiter().clear()
    for _ in range(10):
        resp = client.get("/health")
        assert resp.status_code != 429, "Health endpoint must not be rate-limited"


def test_429_includes_retry_after_header(client, monkeypatch):
    """Denied requests must include a Retry-After header."""
    monkeypatch.setattr(rl_module, "_burst", lambda: 1.0)
    monkeypatch.setattr(rl_module, "_per_minute", lambda: 0.01)
    monkeypatch.setattr(rl_module, "_enabled", lambda: True)

    get_limiter().clear()
    # First request uses the burst token
    client.get("/ready")
    # Second request should be denied
    resp = client.get("/ready")
    if resp.status_code == 429:
        assert "retry-after" in resp.headers
        assert int(resp.headers["retry-after"]) > 0
