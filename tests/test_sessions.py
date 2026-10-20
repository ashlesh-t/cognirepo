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


# ── #208 follow-up: persistence beyond log retention, client at connect, killed servers ──────────────

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402


def _dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _wipe_log(store):
    d = events.events_dir(store)
    for name in os.listdir(d):
        if name.startswith("events.jsonl"):
            os.remove(os.path.join(d, name))


class TestSidecar:
    def test_closed_session_survives_log_rotation(self, store):
        events.record_session(store, "a", client="claude-code", pid=os.getpid(), started="2026-01-01T00:00:00.000000Z")
        events.record_session(store, "a", closed_at="2026-01-01T00:05:00.000000Z",
                              last_activity="2026-01-01T00:05:00.000000Z", call_count=7)
        _wipe_log(store)
        (row,) = events.list_sessions(store)
        assert row["id"] == "a" and row["client"] == "claude-code" and row["call_count"] == 7
        assert row["state"] == "closed" and row["closed_by"] == "session_end"
        assert row["started"] == "2026-01-01T00:00:00.000000Z"

    def test_merge_never_overwrites_with_none(self, store):
        events.record_session(store, "a", client="claude-code", started="2026-01-01T00:00:00.000000Z")
        events.record_session(store, "a", client=None, call_count=3)
        row = json.loads(open(os.path.join(events.events_dir(store), "sessions.json"), encoding="utf-8").read())[0]
        assert row["client"] == "claude-code" and row["call_count"] == 3

    def test_log_and_sidecar_are_merged_not_duplicated(self, store):
        events.record_session(store, "a", started="2026-01-01T00:00:00.000000Z", call_count=40,
                              closed_at="2026-01-01T01:00:00.000000Z")
        events.emit("session.start", store_dir=store, session_id="a", client="c")
        _call(store, "a", "lookup_symbol", "t1")
        rows = events.list_sessions(store)
        assert len(rows) == 1 and rows[0]["call_count"] == 40          # the larger of log (1) and sidecar (40)
        assert rows[0]["started"] == "2026-01-01T00:00:00.000000Z"

    def test_only_the_newest_200_rows_are_kept(self, store):
        for i in range(205):
            events.record_session(store, f"s{i:03d}", started=f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}.000000Z")
        rows = json.loads(open(os.path.join(events.events_dir(store), "sessions.json"), encoding="utf-8").read())
        assert len(rows) == 200 and "s000" not in {r["id"] for r in rows} and "s204" in {r["id"] for r in rows}

    def test_concurrent_writers_lose_no_rows(self, store):
        code = ("import sys; from core import events; "
                "events.record_session(sys.argv[1], sys.argv[2], started='2026-01-01T00:00:00.000000Z')")
        procs = [subprocess.Popen([sys.executable, "-c", code, store, f"p{i}"]) for i in range(8)]
        for p in procs:
            assert p.wait() == 0
        ids = {r["id"] for r in events.list_sessions(store)}
        assert ids == {f"p{i}" for i in range(8)}

    def test_corrupt_sidecar_is_ignored(self, store):
        os.makedirs(events.events_dir(store), exist_ok=True)
        open(os.path.join(events.events_dir(store), "sessions.json"), "w", encoding="utf-8").write("{nope")
        events.emit("session.start", store_dir=store, session_id="a")
        assert [r["id"] for r in events.list_sessions(store)] == ["a"]

    def test_disabled_events_write_nothing(self, store, monkeypatch):
        monkeypatch.setenv("COGNIREPO_EVENTS", "0")
        events.record_session(store, "a", client="c")
        assert not os.path.exists(os.path.join(events.events_dir(store), "sessions.json"))


class TestKilledServers:
    def test_dead_pid_session_is_closed_not_stale(self, store):
        events.emit("session.start", store_dir=store, session_id="k", client="c", pid=_dead_pid())
        (row,) = events.list_sessions(store, now=time.time() + 3600)       # would have been "stale"
        assert row["state"] == "closed" and row["closed_by"] == "process_gone"
        assert row["closed_at"] == row["last_activity"]

    def test_live_pid_with_matching_start_stays_active(self, store):
        import psutil
        events.emit("session.start", store_dir=store, session_id="l", client="c", pid=os.getpid(),
                    proc_start=psutil.Process().create_time())
        (row,) = events.list_sessions(store)
        assert row["state"] == "active" and row["closed_by"] is None

    def test_reused_pid_is_not_mistaken_for_the_server(self, store):
        import psutil
        events.emit("session.start", store_dir=store, session_id="r", client="c", pid=os.getpid(),
                    proc_start=psutil.Process().create_time() - 86400)     # a different, older process
        (row,) = events.list_sessions(store)
        assert row["state"] == "closed" and row["closed_by"] == "process_gone"

    def test_old_sessions_without_a_pid_keep_the_old_rules(self, store):
        events.emit("session.start", store_dir=store, session_id="o", client="c")
        assert events.list_sessions(store, now=time.time() + 3600)[0]["state"] == "stale"

    def test_clean_end_is_session_end(self, store):
        events.emit("session.start", store_dir=store, session_id="e", pid=_dead_pid())
        events.emit("session.end", store_dir=store, session_id="e")
        assert events.list_sessions(store)[0]["closed_by"] == "session_end"

    def test_a_real_killed_process_is_detected(self, store, tmp_path):
        code = ("import sys, time, psutil; from core import events; "
                "events.emit('session.start', store_dir=sys.argv[1], session_id='real', client='c', pid=__import__('os').getpid(), "
                "proc_start=psutil.Process().create_time()); print('up', flush=True); time.sleep(60)")
        proc = subprocess.Popen([sys.executable, "-c", code, store], stdout=subprocess.PIPE, text=True)
        try:
            assert proc.stdout.readline().strip() == "up"
            assert events.list_sessions(store)[0]["state"] == "active"
            proc.kill()
            proc.wait()
            row = events.list_sessions(store)[0]
            assert row["state"] == "closed" and row["closed_by"] == "process_gone"
        finally:
            proc.kill()


class TestClientAtConnect:
    """Drive the real MCP SDK handshake: the client name must be recorded before any tool call."""

    def test_tools_list_announces_the_client(self, store, monkeypatch):
        anyio = pytest.importorskip("anyio")
        mcp_server = pytest.importorskip("interface.server.mcp_server")
        from mcp.shared.memory import create_connected_server_and_client_session
        from mcp import types as mtypes
        monkeypatch.setattr(events, "_default_store", lambda: store)
        monkeypatch.setattr(mcp_server, "_MCP_SESSION", {"session_id": "sess-1"})
        monkeypatch.setattr(mcp_server, "_MCP_CLIENT", None)
        monkeypatch.setattr(mcp_server, "_CLIENT_ANNOUNCED", False)
        monkeypatch.setattr(mcp_server.mcp._mcp_server, "request_handlers",
                            dict(mcp_server.mcp._mcp_server.request_handlers))   # undo the hook after the test
        assert mcp_server._wrap_list_tools_for_client() is True
        assert mcp_server._wrap_list_tools_for_client() is True      # idempotent: no double wrapping

        async def run():
            async with create_connected_server_and_client_session(
                    mcp_server.mcp._mcp_server,
                    client_info=mtypes.Implementation(name="test-client", version="1")) as client:
                await client.list_tools()

        anyio.run(run)
        evs = events.read_since(store, 0)
        got = [e for e in evs if e["type"] == "session.client"]
        assert len(got) == 1 and got[0]["client"] == "test-client" and got[0]["session_id"] == "sess-1"
        (row,) = events.list_sessions(store)
        assert row["client"] == "test-client" and row["call_count"] == 0     # known with zero tool calls

    def test_unknown_sdk_shape_leaves_behaviour_unchanged(self, monkeypatch):
        mcp_server = pytest.importorskip("interface.server.mcp_server")
        monkeypatch.setattr(mcp_server.mcp._mcp_server, "request_handlers", {})
        assert mcp_server._wrap_list_tools_for_client() is False

    def test_session_start_and_end_populate_the_sidecar(self, store, monkeypatch):
        mcp_server = pytest.importorskip("interface.server.mcp_server")
        monkeypatch.setattr(events, "_default_store", lambda: store)
        monkeypatch.setattr(mcp_server, "_MCP_SESSION", {"session_id": "s9"})
        monkeypatch.setattr(mcp_server, "_SESSION_ENDED", False)
        monkeypatch.setattr(mcp_server, "_CALL_COUNT", 5)
        mcp_server._emit_session_event("session.start")
        mcp_server._emit_session_event("session.end")
        _wipe_log(store)
        (row,) = events.list_sessions(store)
        assert row["id"] == "s9" and row["call_count"] == 5 and row["closed_by"] == "session_end"
        assert row["pid"] == os.getpid()
