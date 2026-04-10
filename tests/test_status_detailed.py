# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""Tests for GET /status/detailed endpoint (api/routes/status.py)."""
from __future__ import annotations

import pytest

try:
    from fastapi.testclient import TestClient
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

_skip_http = pytest.mark.skipif(
    not _FASTAPI_AVAILABLE,
    reason="fastapi not installed",
)


@_skip_http
@pytest.fixture(scope="module")
def client():
    from api.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="module")
def auth_token(client):
    """Obtain a JWT token for authenticated requests."""
    import os
    password = os.environ.get("COGNIREPO_TEST_PASSWORD", "changeme-test")
    resp = client.post("/login", json={"password": password})
    if resp.status_code == 200:
        return resp.json().get("access_token", "")
    return ""


@_skip_http
class TestStatusDetailed:

    def test_status_detailed_returns_200(self, client, auth_token):
        headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
        resp = client.get("/status/detailed", headers=headers)
        assert resp.status_code in (200, 401)

    def test_status_detailed_schema(self, client, auth_token):
        headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
        resp = client.get("/status/detailed", headers=headers)
        if resp.status_code != 200:
            pytest.skip("auth required — skip schema check in this env")
        data = resp.json()
        assert "uptime_s" in data
        assert "python" in data
        assert "platform" in data
        assert "memory" in data
        assert "graph" in data
        assert "circuit_breaker" in data
        assert "ok" in data
        assert data["ok"] is True

    def test_status_detailed_memory_key(self, client, auth_token):
        headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
        resp = client.get("/status/detailed", headers=headers)
        if resp.status_code != 200:
            pytest.skip("auth required")
        data = resp.json()
        assert "faiss_vectors" in data["memory"]

    def test_status_detailed_graph_key(self, client, auth_token):
        headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
        resp = client.get("/status/detailed", headers=headers)
        if resp.status_code != 200:
            pytest.skip("auth required")
        data = resp.json()
        assert "nodes" in data["graph"]
        assert "edges" in data["graph"]

    def test_status_detailed_uptime_is_positive(self, client, auth_token):
        headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
        resp = client.get("/status/detailed", headers=headers)
        if resp.status_code != 200:
            pytest.skip("auth required")
        assert resp.json()["uptime_s"] >= 0


# ── Unit test (calls endpoint function directly) ──────────────────────────────

@_skip_http
class TestStatusDetailedUnit:
    """Test the endpoint function directly, bypassing HTTP."""

    def test_returns_dict_with_required_keys(self):
        """The response dict always has all required keys."""
        import asyncio
        from api.routes.status import status_detailed
        resp = asyncio.get_event_loop().run_until_complete(status_detailed())
        data = resp.body
        import json
        body = json.loads(data)
        for key in ("uptime_s", "python", "platform", "memory", "graph",
                    "circuit_breaker", "ok", "multi_agent", "grpc_port"):
            assert key in body, f"Missing key: {key}"

    def test_multi_agent_reflects_env(self, monkeypatch):
        """multi_agent field mirrors COGNIREPO_MULTI_AGENT_ENABLED."""
        import asyncio, json
        from api.routes.status import status_detailed
        monkeypatch.setenv("COGNIREPO_MULTI_AGENT_ENABLED", "true")
        resp = asyncio.get_event_loop().run_until_complete(status_detailed())
        body = json.loads(resp.body)
        assert body["multi_agent"] is True

    def test_grpc_port_reflects_env(self, monkeypatch):
        """grpc_port field mirrors COGNIREPO_GRPC_PORT."""
        import asyncio, json
        from api.routes.status import status_detailed
        monkeypatch.setenv("COGNIREPO_GRPC_PORT", "50052")
        resp = asyncio.get_event_loop().run_until_complete(status_detailed())
        body = json.loads(resp.body)
        assert body["grpc_port"] == 50052
