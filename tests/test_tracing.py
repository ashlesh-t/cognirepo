# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""Tests for api/middleware_tracing.py — X-Trace-Id propagation."""
import pytest

try:
    from fastapi.testclient import TestClient
    _FASTAPI = True
except ImportError:
    _FASTAPI = False

pytestmark = pytest.mark.skipif(not _FASTAPI, reason="fastapi not installed")

from api.main import app


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=False)


def test_tracing_middleware_adds_response_header(client):
    """Every response must carry X-Trace-Id."""
    resp = client.get("/ready")
    assert "x-trace-id" in resp.headers


def test_tracing_middleware_honours_incoming_trace_id(client):
    """If the caller provides X-Trace-Id, the same value is echoed back."""
    resp = client.get("/ready", headers={"X-Trace-Id": "mytest123"})
    assert resp.headers.get("x-trace-id") == "mytest123"


def test_tracing_middleware_generates_trace_id_when_absent(client):
    """Without an incoming trace ID a 32-char hex ID is generated."""
    resp = client.get("/ready")
    tid = resp.headers.get("x-trace-id", "")
    assert len(tid) == 32
    int(tid, 16)   # valid hex
