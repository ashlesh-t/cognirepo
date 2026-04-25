# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Prometheus metrics for CogniRepo.  No-ops if prometheus_client is not installed.
Replaces the former api/metrics.py after the REST API layer was removed.
"""
from __future__ import annotations

try:
    from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST
    _PROM_OK = True
except ImportError:
    _PROM_OK = False


# ── counters / gauges ─────────────────────────────────────────────────────────

class _NoopCounter:
    def labels(self, **_): return self
    def inc(self, _=1): pass

class _NoopGauge:
    def labels(self, **_): return self
    def set(self, _): pass
    def inc(self, _=1): pass
    def dec(self, _=1): pass


if _PROM_OK:
    MEMORY_OPS_TOTAL = Counter(
        "cognirepo_memory_ops_total",
        "Total memory operations",
        ["op", "result"],
    )
    CB_STATE = Gauge(
        "cognirepo_circuit_breaker_state",
        "Circuit breaker state (0=closed, 1=open, 2=half-open)",
    )
    CACHE_HITS = Gauge("cognirepo_cache_hits_total", "Hybrid retrieve cache hits")
    CACHE_MISSES = Gauge("cognirepo_cache_misses_total", "Hybrid retrieve cache misses")
else:
    MEMORY_OPS_TOTAL = _NoopCounter()
    CB_STATE = _NoopGauge()
    CACHE_HITS = _NoopGauge()
    CACHE_MISSES = _NoopGauge()


def metrics_available() -> bool:
    return _PROM_OK


def get_metrics_output() -> tuple[bytes, str]:
    """Return (body_bytes, content_type) for a /metrics HTTP response."""
    if not _PROM_OK:
        return b"prometheus_client not installed\n", "text/plain"
    return generate_latest(), CONTENT_TYPE_LATEST
