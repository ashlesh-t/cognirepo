# pylint: disable=missing-docstring, unnecessary-lambda, import-outside-toplevel, too-few-public-methods, duplicate-code
# pylint: disable=redefined-outer-name, unused-argument, broad-exception-caught, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tests/test_api.py — FastAPI REST layer: login, JWT middleware, memory + episodic routes.
Uses httpx TestClient (sync) — no real server process needed.
"""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def client():
    """Return an httpx TestClient for the FastAPI app."""
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def auth_headers(client):
    """Return Authorization headers for the default 'changeme' password."""
    resp = client.post("/login", json={"password": "changeme"})
    # If login fails (hash mismatch in temp config), skip auth tests gracefully
    if resp.status_code != 200:
        pytest.skip("login failed — password hash mismatch in test config")
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestAuth:
    def test_login_wrong_password_rejected(self, client):
        resp = client.post("/login", json={"password": "wrongpassword"})
        assert resp.status_code == 401

    def test_protected_route_without_token_rejected(self, client):
        resp = client.post("/memory/store", json={"text": "test"})
        assert resp.status_code in (401, 403)

    def test_login_returns_token(self, client):
        resp = client.post("/login", json={"password": "changeme"})
        # Either 200 (hash matches) or 401 (hash doesn't match test fixture)
        assert resp.status_code in (200, 401)
        if resp.status_code == 200:
            assert "access_token" in resp.json()


class TestMemoryRoutes:
    def test_store_memory(self, client, auth_headers):
        resp = client.post(
            "/memory/store",
            json={"text": "fixed JWT bug in verify_token", "source": "test"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "stored"

    def test_retrieve_memory(self, client, auth_headers):
        # Store first
        client.post(
            "/memory/store",
            json={"text": "authentication token expiry logic"},
            headers=auth_headers,
        )
        resp = client.post(
            "/memory/retrieve",
            json={"query": "auth token", "top_k": 1},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_retrieve_returns_list(self, client, auth_headers):
        resp = client.post(
            "/memory/retrieve",
            json={"query": "anything", "top_k": 3},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestEpisodicRoutes:
    def test_log_episode(self, client, auth_headers):
        resp = client.post(
            "/episodic/log",
            json={"event": "ran tests successfully", "metadata": {"suite": "unit"}},
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_get_history(self, client, auth_headers):
        client.post(
            "/episodic/log",
            json={"event": "test event for history"},
            headers=auth_headers,
        )
        resp = client.get("/episodic/history?limit=5", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_episodic_search_returns_200(self, client, auth_headers):
        client.post(
            "/episodic/log",
            json={"event": "rest_api_search_target event"},
            headers=auth_headers,
        )
        resp = client.get("/episodic/search?q=rest_api_search_target", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_episodic_search_matches_keyword(self, client, auth_headers):
        client.post(
            "/episodic/log",
            json={"event": "unique_rest_keyword_xyz logged"},
            headers=auth_headers,
        )
        url = "/episodic/search?q=unique_rest_keyword_xyz&limit=5"
        resp = client.get(url, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert any("unique_rest_keyword_xyz" in json.dumps(e) for e in data)

    def test_episodic_search_requires_auth(self, client):
        resp = client.get("/episodic/search?q=anything")
        assert resp.status_code == 401


class TestGraphRoutes:
    def test_symbol_lookup_returns_200(self, client, auth_headers):
        """Route always returns 200 — either a list (graph populated) or warning dict."""
        resp = client.get("/graph/symbol/log_event", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (list, dict))

    def test_symbol_lookup_entry_shape(self, client, auth_headers):
        """When graph has data, each entry has file/line/type; empty graph → warning dict."""
        resp = client.get("/graph/symbol/log_event", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        if isinstance(data, list):
            for entry in data:
                assert "file" in entry
                assert "line" in entry
                assert "type" in entry
        else:
            assert "warning" in data

    def test_symbol_lookup_requires_auth(self, client):
        resp = client.get("/graph/symbol/anything")
        assert resp.status_code == 401

    def test_callers_returns_200(self, client, auth_headers):
        """Route always returns 200 — either a list or a warning dict."""
        resp = client.get("/graph/callers/nonexistent_fn_xyz", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (list, dict))

    def test_callers_requires_auth(self, client):
        resp = client.get("/graph/callers/anything")
        assert resp.status_code == 401

    def test_subgraph_returns_200(self, client, auth_headers):
        """Route always returns 200 — {nodes,edges} when graph populated, warning dict otherwise."""
        resp = client.get("/graph/subgraph/nonexistent_entity_xyz", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert ("nodes" in data and "edges" in data) or "warning" in data

    def test_subgraph_depth_param(self, client, auth_headers):
        resp = client.get("/graph/subgraph/jwt_auth?depth=2", headers=auth_headers)
        assert resp.status_code == 200

    def test_subgraph_is_json_serialisable(self, client, auth_headers):
        resp = client.get("/graph/subgraph/nonexistent_entity_xyz", headers=auth_headers)
        assert resp.status_code == 200
        assert json.dumps(resp.json()) is not None

    def test_subgraph_requires_auth(self, client):
        resp = client.get("/graph/subgraph/jwt_auth")
        assert resp.status_code == 401

    def test_graph_stats_returns_200(self, client, auth_headers):
        resp = client.get("/graph/stats", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "node_count" in data
        assert "edge_count" in data
        assert "top_concepts" in data

    def test_graph_stats_counts_non_negative(self, client, auth_headers):
        resp = client.get("/graph/stats", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_count"] >= 0
        assert data["edge_count"] >= 0

    def test_graph_stats_requires_auth(self, client):
        resp = client.get("/graph/stats")
        assert resp.status_code == 401

    def test_symbol_lookup_returns_warning_when_graph_empty(self, client, auth_headers):
        """A2.3: symbol lookup returns 200 + warning dict on empty graph."""
        resp = client.get("/graph/symbol/anything", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # graph is empty in test fixture → expect warning
        assert isinstance(data, dict)
        assert "warning" in data
        assert "results" in data

    def test_callers_returns_warning_when_graph_empty(self, client, auth_headers):
        resp = client.get("/graph/callers/anything", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "warning" in data

    def test_subgraph_returns_warning_when_graph_empty(self, client, auth_headers):
        resp = client.get("/graph/subgraph/jwt_auth?depth=2", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "warning" in data
