# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""#208 — sessions derived from the event log, the client name, lifecycle events and /api/v1/sessions."""
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core import events
from interface.ui import security as sec
from interface.ui.app import create_app
from interface.ui.audit import AuditLog
from interface.ui.status import _store_dir

PORT = 8766
TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.delenv("COGNIREPO_EVENTS", raising=False)
    monkeypatch.delenv("COGNIREPO_EVENTS_METADATA_ONLY", raising=False)
    return str(tmp_path / "store")


def _call(store, sid, tool, tid, *, client="claude-code", dur=5, fail=False, **kw):
    events.emit("tool.start", store_dir=store, session_id=sid, client=client, tool=tool, trace_id=tid,
                args_summary=f"query={tool}")
    if fail:
        events.emit("tool.error", store_dir=store, session_id=sid, client=client, tool=tool, trace_id=tid,
                    dur_ms=dur, error="ValueError")
    else:
        events.emit("tool.end", store_dir=store, session_id=sid, client=client, tool=tool, trace_id=tid,
                    dur_ms=dur, result_summary="done", **kw)


class TestListSessions:
    def test_two_sessions_counted_and_ordered(self, store):
        events.emit("session.start", store_dir=store, session_id="a", client=None)
        _call(store, "a", "lookup_symbol", "t1")
        _call(store, "a", "context_pack", "t2")
        events.emit("session.start", store_dir=store, session_id="b", client=None)
        _call(store, "b", "who_calls", "t3", client="gemini-cli")
        rows = {r["id"]: r for r in events.list_sessions(store)}
        assert rows["a"]["call_count"] == 2 and rows["b"]["call_count"] == 1
        assert rows["a"]["client"] == "claude-code" and rows["b"]["client"] == "gemini-cli"
        assert [r["id"] for r in events.list_sessions(store)] == ["b", "a"]   # most recent first

    def test_client_is_null_until_first_call_then_filled(self, store):
        events.emit("session.start", store_dir=store, session_id="a", client=None)
        assert events.list_sessions(store)[0]["client"] is None
        _call(store, "a", "lookup_symbol", "t1")
        assert events.list_sessions(store)[0]["client"] == "claude-code"

    def test_states_active_stale_closed(self, store):
        events.emit("session.start", store_dir=store, session_id="live", client="c")
        events.emit("session.start", store_dir=store, session_id="done", client="c")
        events.emit("session.end", store_dir=store, session_id="done", client="c")
        now = time.time()
        assert {r["id"]: r["state"] for r in events.list_sessions(store, now=now)} == {"live": "active", "done": "closed"}
        later = now + events.SESSION_ACTIVE_SECS + 5
        rows = {r["id"]: r for r in events.list_sessions(store, now=later)}
        assert rows["live"]["state"] == "stale" and rows["live"]["closed_at"] is None
        assert rows["done"]["state"] == "closed" and rows["done"]["closed_at"]

    def test_events_without_session_id_are_ignored(self, store):
        events.emit("watcher.reindex", store_dir=store, reindexed=["a.py"])
        events.emit("service", store_dir=store, service="watcher")
        assert events.list_sessions(store) == []

    def test_reads_across_rotation(self, store, monkeypatch):
        import os
        monkeypatch.setattr(events, "MAX_BYTES", 1500)
        for i in range(12):
            _call(store, "a", "lookup_symbol", f"t{i}")
        assert os.path.exists(events.events_path(store) + ".1")
        # retention is the live file + one backup: sessions span both, older calls have dropped out
        assert 3 <= events.list_sessions(store)[0]["call_count"] < 12


class TestSessionCalls:
    def test_join_start_end_error_and_shed(self, store):
        _call(store, "a", "lookup_symbol", "t1", dur=42)
        _call(store, "a", "context_pack", "t2", fail=True)
        events.emit("tool.start", store_dir=store, session_id="a", tool="who_calls", trace_id="t3")
        events.emit("tool.shed", store_dir=store, session_id="a", tool="store_memory", reason="congestion")
        calls = events.session_calls(store, "a")
        assert [(c["tool"], c["status"]) for c in calls] == [
            ("lookup_symbol", "ok"), ("context_pack", "error"), ("who_calls", "running"), ("store_memory", "shed")]
        assert calls[0]["dur_ms"] == 42 and calls[0]["result_summary"] == "done"
        assert calls[1]["result_summary"] == "ValueError"
        assert calls[3]["result_summary"] == "congestion"

    def test_limit_keeps_the_newest(self, store):
        for i in range(5):
            _call(store, "a", f"tool{i}", f"t{i}")
        assert [c["tool"] for c in events.session_calls(store, "a", limit=2)] == ["tool3", "tool4"]

    def test_other_sessions_excluded_and_unknown_is_none(self, store):
        _call(store, "a", "x", "t1")
        _call(store, "b", "y", "t2")
        assert [c["tool"] for c in events.session_calls(store, "a")] == ["x"]
        assert events.session_calls(store, "nope") is None

    def test_metadata_only_has_no_summaries(self, store, monkeypatch):
        monkeypatch.setenv("COGNIREPO_EVENTS_METADATA_ONLY", "1")
        _call(store, "a", "x", "t1")
        c = events.session_calls(store, "a")[0]
        assert c["args_summary"] is None and c["result_summary"] is None and c["status"] == "ok"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("COGNIREPO_EVENTS", raising=False)
    cfg = sec.SecurityConfig(token=TOKEN, port=PORT, limiter=sec.AttemptLimiter(max_failures=3, base_lockout=60))
    app = create_app(cfg, str(tmp_path), AuditLog(str(tmp_path / "ui" / "audit.log")))
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as c:
        c.store = _store_dir(str(tmp_path))
        yield c


class TestApi:
    def test_requires_token(self, client):
        assert client.get("/api/v1/sessions").status_code == 401
        assert client.get("/api/v1/sessions/a").status_code == 401

    def test_empty_list(self, client):
        r = client.get("/api/v1/sessions", headers=AUTH)
        assert r.status_code == 200 and r.json() == []

    def test_list_and_detail(self, client):
        events.emit("session.start", store_dir=client.store, session_id="s1", client=None)
        _call(client.store, "s1", "lookup_symbol", "t1", dur=7)
        rows = client.get("/api/v1/sessions", headers=AUTH).json()
        assert rows[0]["id"] == "s1" and rows[0]["call_count"] == 1 and rows[0]["client"] == "claude-code"
        d = client.get("/api/v1/sessions/s1?limit=10", headers=AUTH).json()
        assert d["id"] == "s1" and d["calls"][0]["dur_ms"] == 7 and d["calls"][0]["status"] == "ok"

    def test_unknown_session_404_and_bad_id_422(self, client):
        assert client.get("/api/v1/sessions/nope", headers=AUTH).status_code == 404
        assert client.get("/api/v1/sessions/bad%20id", headers=AUTH).status_code == 422
        assert client.get("/api/v1/sessions/a?limit=0", headers=AUTH).status_code == 422


class TestMcpServerSide:
    @pytest.fixture
    def srv(self, store, monkeypatch):
        from interface.server import mcp_server as srv
        monkeypatch.setattr(srv, "_MCP_CLIENT", None)
        monkeypatch.setattr(srv, "_SESSION_ENDED", False)
        monkeypatch.setattr(srv, "_MCP_SESSION", {"session_id": "sess-1"})
        monkeypatch.setattr(events, "_default_store", lambda: store)
        return srv

    def test_client_name_from_handshake_and_cached(self, srv, monkeypatch):
        info = SimpleNamespace(name="  claude-code \n")
        ctx = SimpleNamespace(session=SimpleNamespace(client_params=SimpleNamespace(clientInfo=info)))
        monkeypatch.setattr(srv, "mcp", SimpleNamespace(_mcp_server=SimpleNamespace(request_context=ctx)))
        assert srv._client_name() == "claude-code"
        monkeypatch.setattr(srv, "mcp", SimpleNamespace(_mcp_server=SimpleNamespace()))   # no context any more
        assert srv._client_name() == "claude-code"                                         # cached

    def test_client_name_is_none_outside_a_request(self, srv, monkeypatch):
        monkeypatch.setattr(srv, "mcp", SimpleNamespace(_mcp_server=SimpleNamespace()))
        assert srv._client_name() is None

    def test_tool_events_carry_session_and_client(self, srv, store, monkeypatch):
        monkeypatch.setattr(srv, "_MCP_CLIENT", "gemini-cli")
        srv._emit_tool_event("tool.start", "lookup_symbol", "tid")
        e = events.read_last(store, 1)[0]
        assert e["session_id"] == "sess-1" and e["client"] == "gemini-cli" and e["trace_id"] == "tid"

    def test_session_end_written_once(self, srv, store):
        srv._emit_session_event("session.start")
        srv._emit_session_event("session.end")
        srv._emit_session_event("session.end")   # atexit after the finally: must not duplicate
        assert [e["type"] for e in events.read_last(store, 10)] == ["session.start", "session.end"]
        assert events.list_sessions(store)[0]["state"] == "closed"

    def test_no_session_means_no_event(self, srv, store, monkeypatch):
        monkeypatch.setattr(srv, "_MCP_SESSION", None)
        srv._emit_session_event("session.start")
        assert events.read_last(store, 10) == []
