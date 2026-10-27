# pylint: disable=missing-docstring, redefined-outer-name, unused-argument
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""tests/test_ui_app.py — control API guard + /status (COGNIREPO-129)."""
import json
import os
from unittest import mock

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
        if os.name != "nt":   # Windows has no POSIX permission bits
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


class FakeServices:
    """Stand-in so API tests never spawn processes."""

    def __init__(self):
        self.calls = []

    @staticmethod
    def allowed():
        return ("watcher", "metrics")

    def start(self, name):
        self.calls.append(("start", name))
        return {"name": name, "state": "running", "changed": True}

    def stop(self, name):
        self.calls.append(("stop", name))
        return {"name": name, "state": "stopped", "changed": True}

    def status(self, name=None):
        return [{"name": "watcher", "state": "stopped"}, {"name": "metrics", "state": "stopped"}]

    def shutdown(self):
        pass


@pytest.fixture
def svc_client(tmp_path, audit):
    fake = FakeServices()
    cfg = sec.SecurityConfig(token=TOKEN, port=PORT)
    with TestClient(create_app(cfg, str(tmp_path), audit, services=fake), base_url=f"http://127.0.0.1:{PORT}") as c:
        c.fake = fake
        yield c


class TestServices:
    def test_requires_token(self, svc_client):
        assert svc_client.post("/api/v1/services/watcher/start", json={"confirm": True}).status_code == 401
        assert svc_client.fake.calls == []

    @pytest.mark.parametrize("name", ["bash", "sh", "../etc/passwd", "watcher;ls", "WATCHER", "rm", "python"])
    def test_names_outside_allowlist_rejected(self, svc_client, name):
        r = svc_client.post(f"/api/v1/services/{name}/start", json={"confirm": True}, headers=AUTH)
        assert r.status_code in (404, 405) and svc_client.fake.calls == []

    def test_unknown_name_checked_before_confirm(self, svc_client):
        assert svc_client.post("/api/v1/services/bash/stop", json={}, headers=AUTH).status_code == 404

    @pytest.mark.parametrize("body", [None, {}, {"confirm": False}, {"confirm": "true"}, {"confirm": 1}])
    def test_confirm_required(self, svc_client, body):
        r = svc_client.post("/api/v1/services/watcher/start", json=body, headers=AUTH)
        assert r.status_code in (400, 422) and svc_client.fake.calls == []

    def test_start_stop_with_confirm_and_audited(self, svc_client, audit):
        assert svc_client.post("/api/v1/services/watcher/start", json={"confirm": True}, headers=AUTH).status_code == 200
        assert svc_client.post("/api/v1/services/metrics/stop", json={"confirm": True}, headers=AUTH).status_code == 200
        assert svc_client.fake.calls == [("start", "watcher"), ("stop", "metrics")]
        records = audit.tail()
        assert [r["action"] for r in records] == ["service_start", "service_stop"]
        assert records[0]["service"] == "watcher" and records[0]["result"] == "ok" and TOKEN not in json.dumps(records)

    def test_denials_are_audited_too(self, svc_client, audit):
        svc_client.post("/api/v1/services/bash/start", json={"confirm": True}, headers=AUTH)
        svc_client.post("/api/v1/services/watcher/start", json={}, headers=AUTH)
        assert [r["result"] for r in audit.tail()] == ["denied_unknown_service", "denied_no_confirm"]

    def test_no_generic_exec_or_file_endpoints(self, svc_client):
        paths = set(svc_client.get("/api/v1/openapi.json", headers=AUTH).json()["paths"])
        assert paths == {"/api/v1/session", "/api/v1/status", "/api/v1/graph", "/api/v1/harness",
                         "/api/v1/services", "/api/v1/services/{name}/start", "/api/v1/services/{name}/stop",
                         "/api/v1/insights", "/api/v1/insights/report", "/api/v1/events",
                         "/api/v1/sessions", "/api/v1/sessions/{session_id}", "/api/v1/repos", "/api/v1/graph/changes",
                         "/api/v1/settings/auto-index", "/api/v1/processes", "/api/v1/audit",
                         "/api/v1/daemon", "/api/v1/queue", "/api/v1/journal",
                         "/api/v1/graph/backend", "/api/v1/graph/backend/job",
                         "/api/v1/graph/backend/switch", "/api/v1/graph/backend/migrate"}


class TestServiceManager:
    def test_metrics_start_stop_idempotent_loopback(self):
        from interface.ui.services import ServiceManager
        m = ServiceManager(".", metrics_port=0)
        try:
            a = m.start("metrics")
            assert a["state"] == "running" and a["changed"] is True and a["port"] > 0
            assert m._metrics_server.server_address[0] == "127.0.0.1"
            assert m.start("metrics")["changed"] is False
            assert m.stop("metrics")["state"] == "stopped" and m.stop("metrics")["changed"] is False
        finally:
            m.shutdown()

    @staticmethod
    def _repo(tmp_path, initialised=True):
        (tmp_path / ".cognirepo").mkdir(exist_ok=True)
        cfg = tmp_path / ".cognirepo" / "config.json"
        if initialised:
            cfg.write_text("{}")
        else:
            cfg.unlink(missing_ok=True)
        return str(tmp_path)

    class _Proc:
        def __init__(self, rc=0):
            self._rc = rc

        def poll(self):
            return self._rc

        def wait(self, timeout=None):
            return self._rc

    def test_watcher_spawns_fixed_argv_only(self, monkeypatch, tmp_path):
        import subprocess
        import sys

        from interface.ui import services as S
        seen = {}
        records = iter([None, {"pid": 4242}])
        monkeypatch.setattr(S.ServiceManager, "_watcher_record", lambda self: next(records, {"pid": 4242}))
        monkeypatch.delenv("COGNIREPO_NO_WATCHER", raising=False)

        def fake_popen(argv, **kw):
            seen.update(argv=argv, kw=kw)
            return self._Proc(0)
        monkeypatch.setattr(subprocess, "Popen", fake_popen)
        out = S.ServiceManager(self._repo(tmp_path)).start("watcher")
        assert out["state"] == "running" and out["pid"] == 4242 and out["changed"] is True
        assert seen["argv"] == [sys.executable, "-m", "interface.cli.main", "watch", "--path", str(tmp_path), "--ensure-running"]
        assert seen["kw"].get("shell") is not True
        assert seen["kw"].get("start_new_session") is True or seen["kw"].get("creationflags")   # POSIX | Windows
        assert seen["kw"]["stdout"] is not subprocess.DEVNULL     # output is captured now, not discarded

    def test_watcher_start_is_not_gated_to_linux(self, monkeypatch, tmp_path):
        """#148: the watcher runs on macOS/Windows too; the old 501 'Linux only' gate is gone."""
        from interface.ui import services as S
        records = iter([None, {"pid": 7}])
        monkeypatch.setattr(S.ServiceManager, "_watcher_record", lambda self: next(records, {"pid": 7}))
        monkeypatch.setattr(S.sys, "platform", "win32")
        monkeypatch.delenv("COGNIREPO_NO_WATCHER", raising=False)
        with mock.patch.object(S.subprocess, "Popen", return_value=self._Proc(0)) as popen:
            out = S.ServiceManager(self._repo(tmp_path)).start("watcher")
        assert out["state"] == "running" and popen.called

    def test_watcher_start_on_uninitialised_repo_is_failed_not_starting(self, monkeypatch, tmp_path):
        from interface.ui import services as S
        monkeypatch.setattr(S.ServiceManager, "_watcher_record", lambda self: None)
        monkeypatch.delenv("COGNIREPO_NO_WATCHER", raising=False)
        with mock.patch.object(S.subprocess, "Popen") as popen:
            out = S.ServiceManager(self._repo(tmp_path, initialised=False)).start("watcher")
        assert out["state"] == "failed" and out["reason"] == "not_initialised" and out["changed"] is False
        assert not popen.called

    def test_watcher_start_reports_launcher_failure_with_its_output(self, monkeypatch, tmp_path):
        from interface.ui import services as S
        monkeypatch.setattr(S.ServiceManager, "_watcher_record", lambda self: None)
        monkeypatch.delenv("COGNIREPO_NO_WATCHER", raising=False)
        repo = self._repo(tmp_path)

        def fake_popen(argv, **kw):
            kw["stdout"].write(b"boom: cannot start\n")
            return self._Proc(3)
        with mock.patch.object(S.subprocess, "Popen", side_effect=fake_popen):
            out = S.ServiceManager(repo).start("watcher")
        assert out["state"] == "failed" and out["reason"] == "spawn_failed" and "boom" in out["detail"]

    def test_watcher_start_that_never_registers_stays_starting(self, monkeypatch, tmp_path):
        from interface.ui import services as S
        monkeypatch.setattr(S.ServiceManager, "_watcher_record", lambda self: None)
        monkeypatch.setattr(S, "_START_WAIT_SECS", 0.2)
        monkeypatch.delenv("COGNIREPO_NO_WATCHER", raising=False)
        with mock.patch.object(S.subprocess, "Popen", return_value=self._Proc(0)):
            out = S.ServiceManager(self._repo(tmp_path)).start("watcher")
        assert out["state"] == "starting"

    def test_watcher_start_respects_the_env_kill_switch(self, monkeypatch, tmp_path):
        from interface.ui import services as S
        monkeypatch.setattr(S.ServiceManager, "_watcher_record", lambda self: None)
        monkeypatch.setenv("COGNIREPO_NO_WATCHER", "1")
        out = S.ServiceManager(self._repo(tmp_path)).start("watcher")
        assert out["state"] == "failed" and out["reason"] == "disabled_by_env"

    @pytest.mark.parametrize("outcome,state,detail", [("stopped", "stopped", None), ("killed", "stopped", "needed SIGKILL"),
                                                      ("failed", "failed", None), ("not_found", "stopped", None)])
    def test_watcher_stop_uses_the_escalating_stop(self, monkeypatch, tmp_path, outcome, state, detail):
        from interface.cli import daemon
        from interface.ui import services as S
        calls = []
        monkeypatch.setattr(S.ServiceManager, "_watcher_record", lambda self: {"pid": 99} if not calls else None)
        monkeypatch.setattr(daemon, "stop_watcher_and_wait", lambda pid, **kw: calls.append((pid, kw)) or outcome)
        out = S.ServiceManager(str(tmp_path)).stop("watcher")
        assert out["state"] == state and calls[0][0] == "99"
        assert calls[0][1]["timeout"] == S._STOP_WAIT_SECS       # bounded: a request must not hang for 30 s
        assert out.get("detail") == detail or (state == "failed" and out["reason"] == "stop_failed")

    def test_watcher_stop_refuses_an_embedded_watcher(self, monkeypatch, tmp_path):
        from interface.cli import daemon
        from interface.ui import services as S
        monkeypatch.setattr(S.ServiceManager, "_watcher_record", lambda self: {"pid": 99})
        monkeypatch.setattr(daemon, "stop_watcher_and_wait", lambda *a, **k: "embedded")
        with pytest.raises(S.ServiceError) as ei:
            S.ServiceManager(str(tmp_path)).stop("watcher")
        assert ei.value.status == 409 and ei.value.code == "embedded_watcher"

    def test_metrics_start_without_prometheus_client_is_failed(self, monkeypatch, tmp_path):
        import importlib.util

        from interface.ui import services as S
        real = importlib.util.find_spec
        monkeypatch.setattr(importlib.util, "find_spec", lambda n, *a: None if n == "prometheus_client" else real(n, *a))
        out = S.ServiceManager(str(tmp_path)).start("metrics")
        assert out["state"] == "failed" and out["reason"] == "dependency_missing"


class TestHarness:
    def test_reports_names_only_never_args_or_env(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {
            "cognirepo": {"command": "/usr/bin/cognirepo", "args": ["serve", "--key", "SUPERSECRET"], "env": {"K": "SUPERSECRET"}},
            "other": {"command": "x"}}}))
        (tmp_path / ".cursor").mkdir()
        (tmp_path / ".cursor" / "mcp.json").write_text("{not json")
        r = client.get("/api/v1/harness", headers=AUTH)
        assert r.status_code == 200 and "SUPERSECRET" not in r.text
        by = {c["client"]: c for c in r.json()["clients"]}
        assert by["claude-code"]["registered"] is True
        assert by["claude-code"]["configs"][0]["servers"] == [{"name": "cognirepo", "command": "cognirepo"}]
        assert by["cursor"]["registered"] is False and by["cursor"]["configs"][0]["readable"] is False
        assert "gemini-cli" in by

    def test_last_context_has_fixed_fields_only(self, client, tmp_path, monkeypatch):
        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))      # Path.home() reads this on Windows
        repo = os.path.basename(str(tmp_path))
        d = home / ".cognirepo" / repo
        d.mkdir(parents=True)
        (d / "last_context.json").write_text(json.dumps({"generated_at": "t", "tool": "x", "repo": repo,
                                                         "query": "private question", "sections": [1, 2]}))
        lc = client.get("/api/v1/harness", headers=AUTH).json()["last_context"]
        assert lc == {"generated_at": "t", "tool": "x", "repo": repo, "section_count": 2}


class TestContract:
    def test_committed_openapi_matches_generated(self):
        from interface.ui.openapi import SPEC_PATH, render
        committed = open(SPEC_PATH, encoding="utf-8").read()
        assert committed == render(), "docs/openapi/ui-v1.json is stale: run `python -m interface.ui.openapi --write`"

    def test_security_schemes_and_session_is_the_only_unauthenticated_op(self):
        import json

        from interface.ui.openapi import SPEC_PATH
        spec = json.load(open(SPEC_PATH, encoding="utf-8"))
        assert set(spec["components"]["securitySchemes"]) == {"bearerAuth", "cookieAuth"}
        open_ops = [p for p, ops in spec["paths"].items() for o in ops.values() if o.get("security") == []]
        assert open_ops == ["/api/v1/session"]
        for ops in spec["paths"].values():
            for o in ops.values():
                assert {"403", "429"} <= set(o["responses"])

    def test_every_endpoint_is_documented(self):
        import json

        from interface.ui.openapi import SPEC_PATH
        doc = open(os.path.join(os.path.dirname(SPEC_PATH), "..", "UI_API.md"), encoding="utf-8").read()
        for path in json.load(open(SPEC_PATH, encoding="utf-8"))["paths"]:
            assert path in doc, f"{path} missing from docs/UI_API.md"


class TestReadOnlyProcess:
    def test_ui_never_loads_the_destructive_loaders(self, tmp_path):
        """The UI process must not import ASTIndexer / LocalVectorDB: their load paths can rename or
        sweep live index files while another process is writing (see issue #129)."""
        import subprocess
        import sys
        code = f"""
import sys
from fastapi.testclient import TestClient
from interface.ui import security as sec
from interface.ui.app import create_app
cfg = sec.SecurityConfig(token='t', port=8731)
c = TestClient(create_app(cfg, {str(tmp_path)!r}), base_url='http://127.0.0.1:8731')
h = {{'Authorization': 'Bearer t'}}
for path in ('/api/v1/status', '/api/v1/graph', '/api/v1/harness', '/api/v1/services'):
    assert c.get(path, headers=h).status_code == 200, path
bad = [m for m in sys.modules if m.endswith('ast_indexer') or 'local_vector_db' in m or m == 'faiss']
print('LOADED:' + ','.join(bad))
"""
        env = {**os.environ, "COGNIREPO_GLOBAL_DIR": str(tmp_path / "g")}
        out = subprocess.run([sys.executable, "-c", code], cwd=str(tmp_path), env=env, capture_output=True, text=True, check=False)
        assert out.returncode == 0, out.stderr[-800:]
        assert "LOADED:" in out.stdout and out.stdout.strip().endswith("LOADED:"), out.stdout
