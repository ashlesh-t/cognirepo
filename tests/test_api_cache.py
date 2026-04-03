# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tests/test_api_cache.py — Sprint 5 / TASK-016 acceptance tests.

Covers:
  - cache_get / cache_set round-trip with a mocked Redis client
  - Graceful degradation when Redis is not available (no crash, returns None)
  - cache_invalidate_prefix deletes keys with the right prefix
  - redis_status() returns connected=True / False correctly
  - /memory/retrieve and /graph/symbol routes use cache (Redis hit avoids tool call)
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_mock_redis(data: dict | None = None):
    """Return a mock Redis client backed by an in-memory dict."""
    store: dict = data or {}
    client = MagicMock()
    client.ping.return_value = True

    def _get(key):
        val = store.get(key)
        return val.encode() if isinstance(val, str) else val

    def _setex(key, ttl, value):
        store[key] = value if isinstance(value, str) else value.decode()

    def _delete(*keys):
        for k in keys:
            store.pop(k if isinstance(k, str) else k.decode(), None)

    def _keys(pattern):
        prefix = pattern.rstrip("*")
        return [k.encode() for k in store if k.startswith(prefix)]

    client.get.side_effect = _get
    client.setex.side_effect = _setex
    client.delete.side_effect = _delete
    client.keys.side_effect = _keys
    return client, store


# ── cache_get / cache_set ─────────────────────────────────────────────────────

class TestCacheGetSet:
    def setup_method(self):
        from api.cache import reset_for_testing
        reset_for_testing()

    def test_cache_miss_returns_none(self):
        mock_client, _ = _make_mock_redis()
        with patch("api.cache._init_redis", return_value=mock_client):
            from api.cache import cache_get
            result = cache_get("nonexistent_key")
        assert result is None

    def test_cache_set_then_get(self):
        mock_client, store = _make_mock_redis()
        with patch("api.cache._init_redis", return_value=mock_client):
            from api.cache import cache_get, cache_set
            cache_set("mykey", {"answer": 42}, ttl=300)
            result = cache_get("mykey")
        assert result == {"answer": 42}

    def test_cache_set_stores_json(self):
        mock_client, store = _make_mock_redis()
        with patch("api.cache._init_redis", return_value=mock_client):
            from api.cache import cache_set
            cache_set("k", [1, 2, 3], ttl=60)
        assert "k" in store
        assert json.loads(store["k"]) == [1, 2, 3]

    def test_cache_set_uses_correct_ttl(self):
        mock_client, _ = _make_mock_redis()
        with patch("api.cache._init_redis", return_value=mock_client):
            from api.cache import cache_set
            cache_set("k", "v", ttl=999)
        mock_client.setex.assert_called_once()
        call_args = mock_client.setex.call_args
        assert call_args[0][1] == 999  # ttl is second positional arg


# ── graceful degradation ──────────────────────────────────────────────────────

class TestGracefulDegradation:
    def setup_method(self):
        from api.cache import reset_for_testing
        reset_for_testing()

    def test_cache_get_returns_none_when_redis_unavailable(self):
        with patch("api.cache._init_redis", return_value=None):
            from api.cache import cache_get
            result = cache_get("any_key")
        assert result is None

    def test_cache_set_does_not_raise_when_unavailable(self):
        with patch("api.cache._init_redis", return_value=None):
            from api.cache import cache_set
            cache_set("k", "v")  # must not raise

    def test_cache_get_does_not_raise_on_redis_error(self):
        broken = MagicMock()
        broken.get.side_effect = Exception("connection refused")
        with patch("api.cache._init_redis", return_value=broken):
            from api.cache import cache_get
            result = cache_get("k")
        assert result is None

    def test_redis_init_failure_caught(self, monkeypatch):
        """If redis.from_url raises, _init_redis returns None gracefully."""
        from api.cache import reset_for_testing
        reset_for_testing()
        monkeypatch.setenv("COGNIREPO_REDIS_URL", "redis://bad_host:9999")
        with patch("redis.from_url", side_effect=Exception("connection error")):
            from api import cache as c
            c._redis_checked = False  # force re-init
            result = c._init_redis()
        assert result is None


# ── cache_invalidate_prefix ───────────────────────────────────────────────────

class TestCacheInvalidatePrefix:
    def setup_method(self):
        from api.cache import reset_for_testing
        reset_for_testing()

    def test_deletes_matching_keys(self):
        mock_client, store = _make_mock_redis({
            "retrieve:abc": '{"x":1}',
            "retrieve:def": '{"x":2}',
            "lookup_symbol:foo": '"bar"',
        })
        with patch("api.cache._init_redis", return_value=mock_client):
            from api.cache import cache_invalidate_prefix
            cache_invalidate_prefix("retrieve")
        # retrieve:* keys should be gone; lookup_symbol stays
        assert "retrieve:abc" not in store
        assert "retrieve:def" not in store
        assert "lookup_symbol:foo" in store

    def test_no_op_when_redis_unavailable(self):
        with patch("api.cache._init_redis", return_value=None):
            from api.cache import cache_invalidate_prefix
            cache_invalidate_prefix("retrieve")  # must not raise


# ── redis_status ──────────────────────────────────────────────────────────────

class TestRedisStatus:
    def setup_method(self):
        from api.cache import reset_for_testing
        reset_for_testing()

    def test_connected_true_when_redis_up(self):
        mock_client, _ = _make_mock_redis()
        with patch("api.cache._init_redis", return_value=mock_client):
            from api.cache import redis_status
            status = redis_status()
        assert status["connected"] is True

    def test_connected_false_when_redis_down(self):
        with patch("api.cache._init_redis", return_value=None):
            from api.cache import redis_status
            status = redis_status()
        assert status["connected"] is False
        assert status["url"] is None

    def test_connected_false_on_ping_error(self):
        broken = MagicMock()
        broken.ping.side_effect = Exception("timeout")
        with patch("api.cache._init_redis", return_value=broken):
            from api.cache import redis_status
            status = redis_status()
        assert status["connected"] is False
        assert "error" in status


# ── route-level cache integration ─────────────────────────────────────────────

class TestRouteCacheIntegration:
    """Verify that retrieve and symbol_lookup routes use the cache."""

    def test_retrieve_route_uses_cache_on_hit(self):
        """Second call to /retrieve with same args must NOT call retrieve_memory."""
        cached_value = [{"text": "cached result", "importance": 0.9, "source": "memory"}]
        cache_key = f"retrieve:{hash(('hello', 5))}"

        from api.cache import reset_for_testing
        reset_for_testing()

        with patch("api.cache._init_redis", return_value=_make_mock_redis()[0]):
            from api.cache import cache_set, cache_get
            cache_set(cache_key, cached_value)

            with patch("api.routes.memory.retrieve_memory") as mock_retrieve:
                with patch("api.routes.memory.cache_get", side_effect=lambda k: cached_value if k == cache_key else None):
                    from api.routes.memory import retrieve, RetrieveRequest
                    req = RetrieveRequest(query="hello", top_k=5)
                    result = retrieve(req)

            mock_retrieve.assert_not_called()
            assert result == cached_value

    def test_symbol_lookup_route_uses_cache_on_hit(self):
        """Second call to /graph/symbol/{name} must NOT call indexer when cached."""
        cached_value = [{"file": "auth.py", "line": 10, "type": "FUNCTION"}]

        with patch("api.routes.graph.cache_get", return_value=cached_value):
            with patch("api.routes.graph._get_indexer") as mock_indexer:
                from api.routes.graph import symbol_lookup
                result = symbol_lookup("verify_token")

        mock_indexer.assert_not_called()
        assert result == cached_value
