# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
api/cache.py — Optional Redis cache layer for the CogniRepo REST API.

The REST API runs in a separate process from the MCP/CLI path, so it cannot
share the in-process LRU/TTL caches.  This module provides a thin Redis wrapper
with graceful degradation: if Redis is not running or not configured, all
cache_get() calls return None and cache_set() calls are no-ops.

Enable via .cognirepo/config.json:
    {"redis": {"enabled": true, "url": "redis://localhost:6379"}}

Or via environment variable (takes precedence over config):
    COGNIREPO_REDIS_URL=redis://localhost:6379
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

log = logging.getLogger(__name__)

# Module-level singletons — initialised once on first use
_redis_client: Any = None   # redis.Redis instance or None
_redis_checked: bool = False


def _init_redis() -> Any:
    """Connect to Redis once; cache the result (None if unavailable)."""
    global _redis_client, _redis_checked  # pylint: disable=global-statement
    if _redis_checked:
        return _redis_client
    _redis_checked = True

    # Env var overrides config
    redis_url = os.getenv("COGNIREPO_REDIS_URL", "")

    if not redis_url:
        # Read from .cognirepo/config.json
        try:
            from config.paths import get_path  # pylint: disable=import-outside-toplevel
            cfg_path = get_path("config.json")
            if os.path.exists(cfg_path):
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = json.load(f)
                redis_cfg = cfg.get("redis", {})
                if not redis_cfg.get("enabled", False):
                    log.debug("Redis disabled in config — API cache inactive")
                    return None
                redis_url = redis_cfg.get("url", "redis://localhost:6379")
        except Exception:  # pylint: disable=broad-except
            pass

    if not redis_url:
        return None

    try:
        import redis  # pylint: disable=import-outside-toplevel
        client = redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        _redis_client = client
        log.info("[cache] Redis connected: %s", redis_url)
    except Exception as exc:  # pylint: disable=broad-except
        log.info("[cache] Redis unavailable (%s) — API caching disabled", exc)
        _redis_client = None

    return _redis_client


def cache_get(key: str) -> Optional[Any]:
    """Return a cached value, or None on miss / Redis unavailable."""
    client = _init_redis()
    if client is None:
        return None
    try:
        raw = client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:  # pylint: disable=broad-except
        return None


def cache_set(key: str, value: Any, ttl: int = 300) -> None:
    """Store *value* under *key* with a TTL (seconds). No-op if unavailable."""
    client = _init_redis()
    if client is None:
        return
    try:
        client.setex(key, ttl, json.dumps(value))
    except Exception:  # pylint: disable=broad-except
        pass


def cache_invalidate_prefix(prefix: str) -> None:
    """Delete all keys matching ``prefix:*``. No-op if Redis unavailable."""
    client = _init_redis()
    if client is None:
        return
    try:
        keys = client.keys(f"{prefix}:*")
        if keys:
            client.delete(*keys)
    except Exception:  # pylint: disable=broad-except
        pass


def redis_status() -> dict:
    """Return Redis connection status dict (used by cognirepo doctor)."""
    client = _init_redis()
    if client is None:
        return {"connected": False, "url": None}
    try:
        client.ping()
        # Extract URL from connection pool kwargs
        pool_kwargs = getattr(client, "connection_pool", None)
        conn_kwargs = getattr(pool_kwargs, "connection_kwargs", {}) if pool_kwargs else {}
        host = conn_kwargs.get("host", "?")
        port = conn_kwargs.get("port", "?")
        return {"connected": True, "url": f"redis://{host}:{port}"}
    except Exception as exc:  # pylint: disable=broad-except
        return {"connected": False, "error": str(exc)}


def reset_for_testing() -> None:
    """Reset module singletons — used only in tests."""
    global _redis_client, _redis_checked  # pylint: disable=global-statement
    _redis_client = None
    _redis_checked = False
