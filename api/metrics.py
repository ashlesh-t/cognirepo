# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Prometheus-compatible metrics for CogniRepo.

All metrics are optional — if ``prometheus_client`` is not installed the
module still loads cleanly; `metrics_available()` returns False and the
`/metrics` route returns HTTP 501.

Counters / histograms are created once at module import and shared across
the process.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── optional prometheus import ────────────────────────────────────────────────

try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST, REGISTRY
    _PROM_AVAILABLE = True
except ImportError:
    _PROM_AVAILABLE = False
    logger.debug("prometheus_client not installed — /metrics will return 501")


def metrics_available() -> bool:
    """Return True if prometheus_client is installed."""
    return _PROM_AVAILABLE


# ── metric definitions (only created when prometheus_client is present) ────────

if _PROM_AVAILABLE:
    REQUESTS_TOTAL = Counter(
        "cognirepo_http_requests_total",
        "Total HTTP requests by route and status code",
        ["route", "status"],
    )
    REQUEST_LATENCY = Histogram(
        "cognirepo_http_request_seconds",
        "HTTP request duration in seconds",
        ["route"],
    )
    MEMORY_OPS_TOTAL = Counter(
        "cognirepo_memory_ops_total",
        "Memory operations (store/retrieve/prune) by result",
        ["op", "result"],
    )
    RETRIEVAL_LATENCY = Histogram(
        "cognirepo_retrieval_seconds",
        "Retrieval latency in seconds by signal type",
        ["signal"],
    )
    INDEX_SIZE = Gauge(
        "cognirepo_faiss_vectors",
        "Number of vectors stored in the FAISS index",
    )
    GRAPH_NODES = Gauge(
        "cognirepo_graph_nodes",
        "Number of nodes in the knowledge graph",
    )
    GRAPH_EDGES = Gauge(
        "cognirepo_graph_edges",
        "Number of edges in the knowledge graph",
    )
    CB_STATE = Gauge(
        "cognirepo_circuit_breaker_state",
        "Circuit breaker state: 0=CLOSED 1=HALF_OPEN 2=OPEN",
    )
    RATE_LIMIT_DENIED = Counter(
        "cognirepo_rate_limit_denied_total",
        "Number of requests rejected by the rate limiter",
        ["client_id"],
    )

    def get_metrics_output() -> tuple[bytes, str]:
        """Return (body_bytes, content_type) for the /metrics endpoint."""
        return generate_latest(REGISTRY), CONTENT_TYPE_LATEST

else:
    # Stub objects that silently no-op so call sites don't need guards
    class _Noop:  # pylint: disable=too-few-public-methods
        def labels(self, **_kw):
            return self
        def inc(self, _amount=1):
            pass
        def observe(self, _amount):
            pass
        def set(self, _value):
            pass

    _noop = _Noop()
    REQUESTS_TOTAL = _noop
    REQUEST_LATENCY = _noop
    RETRIEVAL_LATENCY = _noop
    MEMORY_OPS_TOTAL = _noop
    INDEX_SIZE = _noop
    GRAPH_NODES = _noop
    GRAPH_EDGES = _noop
    CB_STATE = _noop
    RATE_LIMIT_DENIED = _noop

    def get_metrics_output() -> tuple[bytes, str]:  # type: ignore[misc]
        raise RuntimeError("prometheus_client not installed")
