# pylint: disable=missing-docstring, redefined-outer-name, unused-argument
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""tests/test_ui_app.py — control API guard + /status (COGNIREPO-129)."""
import json
import os

import pytest
from fastapi.testclient import TestClient

from interface.ui import security as sec
from interface.ui.app import create_app
from interface.ui.audit import AuditLog

PORT = 8765
TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz0123456789"


@pytest.fixture
def audit(tmp_path):
    return AuditLog(str(tmp_path / "ui" / "audit.log"))


@pytest.fixture
def client(tmp_path, audit):
    cfg = sec.SecurityConfig(token=TOKEN, port=PORT, limiter=sec.AttemptLimiter(max_failures=3, base_lockout=60))
    app = create_app(cfg, str(tmp_path), audit)
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as c:
        yield c


AUTH = {"Authorization": f"Bearer {TOKEN}"}


class TestTokenRequired:
    def test_no_token_is_401(self, client):
        assert client.get("/api/v1/status").status_code == 401

    def test_wrong_token_is_401(self, client):
        assert client.get("/api/v1/status", headers={"Authorization": "Bearer nope"}).status_code == 401

    def test_right_token_is_200(self, client):
        r = client.get("/api/v1/status", headers=AUTH)
        assert r.status_code == 200 and r.json()["api_version"] == "1"

    def test_unknown_path_requires_token_too(self, client):
        assert client.get("/api/v1/nope").status_code == 401
        assert client.get("/api/v1/nope", headers=AUTH).status_code == 404


class TestHostOrigin:
    def test_bad_host_rejected(self, client):
        assert client.get("/api/v1/status", headers={**AUTH, "Host": "evil.com"}).status_code == 403

    def test_bad_origin_rejected_even_with_token(self, client):
        for origin in ("https://evil.com", "null", "http://127.0.0.1:1"):
            assert client.get("/api/v1/status", headers={**AUTH, "Origin": origin}).status_code == 403

    def test_good_origin_ok_and_no_wildcard_cors(self, client):
        r = client.get("/api/v1/status", headers={**AUTH, "Origin": f"http://127.0.0.1:{PORT}"})
        assert r.status_code == 200
        assert "access-control-allow-origin" not in r.headers


class TestRateLimit:
    def test_lockout_after_repeated_bad_tokens_blocks_even_good_token(self, client):
        bad = {"Authorization": "Bearer wrong"}
        assert [client.get("/api/v1/status", headers=bad).status_code for _ in range(3)] == [401, 401, 401]
        r = client.get("/api/v1/status", headers=AUTH)
        assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0

    def test_missing_token_does_not_count_as_attack(self, client):
        for _ in range(10):
            assert client.get("/api/v1/status").status_code == 401
        assert client.get("/api/v1/status", headers=AUTH).status_code == 200


class TestSession:
    def test_session_sets_httponly_strict_cookie_then_cookie_authenticates(self, client):
        r = client.post("/api/v1/session", json={"token": TOKEN})
        assert r.status_code == 200
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
        assert client.get("/api/v1/status").status_code == 200  # cookie jar carries it

    def test_bad_session_token_is_401_and_counts(self, client):
        for _ in range(3):
            assert client.post("/api/v1/session", json={"token": "bad"}).status_code == 401
        assert client.post("/api/v1/session", json={"token": TOKEN}).status_code == 429


class TestHeadersAndAudit:
    def test_security_headers(self, client):
        h = client.get("/api/v1/status", headers=AUTH).headers
        assert "default-src 'self'" in h["content-security-policy"]
        assert h["x-content-type-options"] == "nosniff" and h["cache-control"] == "no-store"

    def test_audit_never_contains_token(self, client, audit):
        client.post("/api/v1/session", json={"token": TOKEN})
        client.post("/api/v1/session", json={"token": "bad"})
        raw = open(audit.path, encoding="utf-8").read()
        assert TOKEN not in raw and "session_created" in raw and "session_denied" in raw
        assert oct(os.stat(audit.path).st_mode & 0o777) == "0o600"

    def test_audit_drops_secret_fields_and_rotates(self, tmp_path):
        log = AuditLog(str(tmp_path / "a.log"), max_bytes=200)
        for i in range(20):
            log.log("x", i=i, token="SECRET")
        assert "SECRET" not in open(log.path, encoding="utf-8").read()
        assert os.path.exists(log.path + ".1") and log.tail(3)[-1]["i"] == 19


class TestStatusShape:
    def test_status_fields_and_read_only(self, client):
        data = client.get("/api/v1/status", headers=AUTH).json()
        assert set(data) >= {"api_version", "version", "repo", "daemon", "mcp", "indexer", "ui"}
        assert data["daemon"]["state"] in {"running", "stale", "stopped"}
        assert data["mcp"]["tool_count"] > 0
        json.dumps(data)  # serialisable


class TestGraph:
    @pytest.fixture
    def seeded(self, isolated_cognirepo):
        from data.graph.knowledge_graph import EdgeType, KnowledgeGraph, NodeType
        from interface.tools import graph_view
        graph_view.reset_cache()
        kg = KnowledgeGraph()
        kg.add_node("a.py", NodeType.FILE)
        for i in range(5):
            kg.add_node(f"a.py::f{i}", NodeType.FUNCTION, file="a.py", line=i, secret="SHOULD-NOT-LEAK")
            kg.add_edge(f"a.py::f{i}", "a.py", EdgeType.DEFINED_IN, internal="x")
        kg.add_node("b.py::far", NodeType.FUNCTION, file="b.py")
        kg.add_edge("a.py::f0", "b.py::far", EdgeType.CALLED_BY)
        kg.save()
        yield kg
        graph_view.reset_cache()

    def test_overview_and_bounds(self, client, seeded):
        d = client.get("/api/v1/graph?limit=3", headers=AUTH).json()
        assert d["stats"]["nodes"] == 7 and len(d["nodes"]) == 3 and d["truncated"] is True
        assert client.get("/api/v1/graph?limit=2001", headers=AUTH).status_code == 422
        assert client.get("/api/v1/graph?depth=9", headers=AUTH).status_code == 422

    def test_neighbourhood_depth(self, client, seeded):
        one = client.get("/api/v1/graph?node=a.py::f1&depth=1", headers=AUTH).json()
        ids1 = {n["id"] for n in one["nodes"]}
        assert ids1 == {"a.py::f1", "a.py"}
        two = client.get("/api/v1/graph?node=a.py::f1&depth=3", headers=AUTH).json()
        assert "b.py::far" in {n["id"] for n in two["nodes"]}

    def test_unknown_node_and_whitelisted_attrs(self, client, seeded):
        assert client.get("/api/v1/graph?node=nope", headers=AUTH).json()["found"] is False
        raw = client.get("/api/v1/graph?node=a.py::f1&depth=1", headers=AUTH).text
        assert "SHOULD-NOT-LEAK" not in raw and "internal" not in raw

    def test_graph_view_is_read_only(self, client, seeded):
        pkl = os.path.join(".cognirepo", "graph", "graph.pkl")
        before = os.stat(pkl).st_mtime_ns
        client.get("/api/v1/graph", headers=AUTH)
        client.get("/api/v1/graph?node=a.py::f2&depth=2", headers=AUTH)
        assert os.stat(pkl).st_mtime_ns == before
        assert not os.path.exists(os.path.join(".cognirepo", "graph", "graph.journal"))

    def test_missing_graph_is_empty_not_error(self, client, isolated_cognirepo):
        from interface.tools import graph_view
        graph_view.reset_cache()
        d = client.get("/api/v1/graph", headers=AUTH).json()
        assert d["stats"] == {"nodes": 0, "edges": 0} and d["nodes"] == []
