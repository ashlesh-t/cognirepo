# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""Tests for api/metrics.py — Prometheus metrics."""
import pytest

try:
    from fastapi.testclient import TestClient
    _FASTAPI = True
except ImportError:
    _FASTAPI = False

pytestmark = pytest.mark.skipif(not _FASTAPI, reason="fastapi not installed")

#removed: from api.main import app
from server.metrics import metrics_available


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=False)


def test_metrics_endpoint_exists(client):
    """GET /metrics must return 200 (with prometheus_client) or 501 (without)."""
    resp = client.get("/metrics")
    assert resp.status_code in (200, 501)


def test_metrics_content_when_available(client):
    """If prometheus_client is installed, /metrics returns Prometheus text format."""
    if not metrics_available():
        pytest.skip("prometheus_client not installed")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers.get("content-type", "")
    # At minimum the endpoint itself should have generated some metric lines
    assert b"cognirepo_" in resp.content or b"# HELP" in resp.content


def test_metrics_501_when_unavailable(client, monkeypatch):
    """Without prometheus_client, /metrics returns 501 with an informative message."""
    import api.metrics as m
    monkeypatch.setattr(m, "_PROM_AVAILABLE", False)
    resp = client.get("/metrics")
    assert resp.status_code == 501
    assert "prometheus_client" in resp.text


def test_memory_ops_counter_increments():
    """MEMORY_OPS_TOTAL counter must increment on each call (when prometheus installed)."""
    if not metrics_available():
        pytest.skip("prometheus_client not installed")

    from server.metrics import MEMORY_OPS_TOTAL
    from prometheus_client import REGISTRY

    # Read current value — Counter family name is without _total in some prom versions;
    # check by sample name to be version-agnostic.
    def _get_count(op, result):
        for metric in REGISTRY.collect():
            for sample in metric.samples:
                if (sample.name == "cognirepo_memory_ops_total"
                        and sample.labels.get("op") == op
                        and sample.labels.get("result") == result):
                    return sample.value
        return 0.0

    before = _get_count("store", "ok")
    MEMORY_OPS_TOTAL.labels(op="store", result="ok").inc()
    after = _get_count("store", "ok")
    assert after == before + 1


def test_circuit_breaker_gauge_updates():
    """CB_STATE gauge must reflect state transitions."""
    if not metrics_available():
        pytest.skip("prometheus_client not installed")

    from server.metrics import CB_STATE
    from prometheus_client import REGISTRY

    def _get_gauge():
        for metric in REGISTRY.collect():
            for sample in metric.samples:
                if sample.name == "cognirepo_circuit_breaker_state":
                    return sample.value
        return None

    CB_STATE.set(2)   # simulate OPEN
    assert _get_gauge() == 2.0
    CB_STATE.set(0)   # back to CLOSED
    assert _get_gauge() == 0.0
