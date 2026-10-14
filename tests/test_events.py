# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""#207 — the live event log (core.events) and its SSE feed (interface.ui.event_stream / GET /api/v1/events)."""
import asyncio
import json
import multiprocessing
import os
import threading
import time

import httpx
import pytest

from core import events
from interface.ui import event_stream
from interface.ui import server as ui_server
from interface.ui.status import _store_dir


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.delenv("COGNIREPO_EVENTS", raising=False)
    monkeypatch.delenv("COGNIREPO_EVENTS_METADATA_ONLY", raising=False)
    return str(tmp_path / "store")


def _lines(store):
    with open(events.events_path(store), encoding="utf-8") as fh:
        return [json.loads(x) for x in fh]


class TestEmit:
    def test_seq_is_monotonic_and_file_is_private(self, store):
        seqs = [events.emit("tool.end", store_dir=store, tool="t") for _ in range(3)]
        assert seqs == [1, 2, 3]
        assert [e["seq"] for e in _lines(store)] == [1, 2, 3]
        assert oct(os.stat(events.events_path(store)).st_mode & 0o777) == "0o600"

    def test_secret_named_fields_and_args_are_dropped(self, store):
        events.emit("tool.start", store_dir=store, tool="t", token="SECRET", password="p",
                    args_summary=events.summarize_args({"query": "find x", "api_key": "SECRET", "token": "SECRET"}))
        text = open(events.events_path(store), encoding="utf-8").read()
        assert "SECRET" not in text and "find x" in text

    def test_summaries_are_clipped_and_lists_capped(self, store):
        events.emit("graph.delta", store_dir=store, result_summary="x" * 5000, nodes=[f"n{i}" for i in range(500)])
        e = _lines(store)[0]
        assert len(e["result_summary"]) <= 200 and len(e["nodes"]) == 50 and e["nodes_truncated"] is True

    def test_metadata_only_omits_summaries(self, store, monkeypatch):
        monkeypatch.setenv("COGNIREPO_EVENTS_METADATA_ONLY", "1")
        events.emit("tool.end", store_dir=store, tool="t", args_summary="private", result_summary="private", dur_ms=3)
        e = _lines(store)[0]
        assert "args_summary" not in e and "result_summary" not in e and e["dur_ms"] == 3

    def test_disabled_writes_nothing(self, store, monkeypatch):
        monkeypatch.setenv("COGNIREPO_EVENTS", "0")
        assert events.emit("tool.end", store_dir=store) is None
        assert not os.path.exists(events.events_path(store))

    def test_never_raises_and_never_blocks_on_a_held_lock(self, store, monkeypatch):
        from filelock import FileLock
        os.makedirs(events.events_dir(store))
        with FileLock(os.path.join(events.events_dir(store), "events.lock")):
            t0 = time.monotonic()
            assert events.emit("tool.end", store_dir=store) is None      # lock held by someone else
        assert time.monotonic() - t0 < 2
        monkeypatch.setattr(events, "_emit", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
        assert events.emit("tool.end", store_dir=store) is None

    def test_rotation_keeps_seq_going_and_read_since_spans_both_files(self, store, monkeypatch):
        monkeypatch.setattr(events, "MAX_BYTES", 600)
        for i in range(12):
            events.emit("tool.end", store_dir=store, tool=f"t{i}")
        assert os.path.exists(events.events_path(store) + ".1")
        got = events.read_since(store, 0, limit=100)
        seqs = [e["seq"] for e in got]
        assert seqs == sorted(seqs) and seqs[-1] == 12 and len(set(seqs)) == len(seqs)
        assert [e["seq"] for e in events.read_since(store, 10)] == [11, 12]

    def test_counter_recovers_when_the_sidecar_is_lost(self, store):
        events.emit("tool.end", store_dir=store)
        events.emit("tool.end", store_dir=store)
        os.unlink(os.path.join(events.events_dir(store), "events.seq"))
        assert events.emit("tool.end", store_dir=store) == 3

    def test_concurrent_writers_never_duplicate_a_seq(self, store):
        def worker():
            for _ in range(20):
                events.emit("tool.end", store_dir=store)
        procs = [multiprocessing.get_context("spawn").Process(target=_proc_worker, args=(store,)) for _ in range(3)]
        threads = [threading.Thread(target=worker) for _ in range(3)]
        for p in procs + threads:
            p.start()
        for p in procs + threads:
            p.join(60)
        seqs = [e["seq"] for e in _lines(store)]
        assert len(seqs) == len(set(seqs)) and seqs == sorted(seqs)


def _proc_worker(store):
    from core import events as ev
    for _ in range(20):
        ev.emit("tool.end", store_dir=store)


class TestFilters:
    def test_type_globs_and_session(self):
        e = {"type": "tool.end", "session_id": "s1"}
        assert events.matches(e) and events.matches(e, "s1", ("tool.*",)) and not events.matches(e, "s2")
        assert not events.matches(e, None, ("watcher.*", "graph.delta"))
        assert events.parse_types(" tool.* , ,graph.delta") == ("tool.*", "graph.delta")


class TestTailer:
    def test_follows_new_lines_and_partial_lines(self, store):
        events.emit("a", store_dir=store)
        t = events.Tailer(store)
        assert t.poll() == []                                  # starts at the end: only new events
        events.emit("b", store_dir=store)
        assert [e["type"] for e in t.poll()] == ["b"]
        with open(events.events_path(store), "ab") as fh:      # a writer caught mid-line
            fh.write(b'{"seq": 99, "type": "c"')
        assert t.poll() == []
        with open(events.events_path(store), "ab") as fh:
            fh.write(b"}\n")
        assert [e["seq"] for e in t.poll()] == [99]

    def test_survives_rotation_without_losing_the_tail_of_the_old_file(self, store, monkeypatch):
        monkeypatch.setattr(events, "MAX_BYTES", 400)
        events.emit("a", store_dir=store)
        t = events.Tailer(store)
        got = []
        for i in range(10):
            events.emit("x", store_dir=store, n=i)
            got += t.poll()
        got += t.poll()
        assert [e["n"] for e in got] == list(range(10))


def _run(coro):
    return asyncio.run(coro)


async def _collect(gen, n, timeout=5):
    out = []
    async def go():
        async for frame in gen:
            out.append(frame)
            if len(out) >= n:
                return
    await asyncio.wait_for(go(), timeout)
    await gen.aclose()
    return out


class TestStream:
    def test_frames_resume_and_filters(self, store, monkeypatch):
        monkeypatch.setattr(event_stream, "POLL_SECS", 0.02)
        for i in range(3):
            events.emit("tool.end", store_dir=store, session_id="s1", n=i)
        events.emit("watcher.reindex", store_dir=store, session_id="s2")

        async def never():
            return False
        frames = _run(_collect(event_stream.stream(never, store, after=1, types=("tool.*",)), 3))
        assert frames[0] == f"retry: {event_stream.RETRY_MS}\n\n"
        assert frames[1].startswith("id: 2\nevent: tool.end\ndata: ") and frames[2].startswith("id: 3\n")
        assert json.loads(frames[1].split("data: ", 1)[1])["n"] == 1

    def test_live_events_arrive_and_dupes_do_not(self, store, monkeypatch):
        monkeypatch.setattr(event_stream, "POLL_SECS", 0.02)
        events.emit("tool.end", store_dir=store, n=0)

        async def never():
            return False

        async def scenario():
            gen = event_stream.stream(never, store, replay=1)
            task = asyncio.create_task(_collect(gen, 3))
            await asyncio.sleep(0.2)
            await asyncio.to_thread(events.emit, "tool.end", store_dir=store, n=1)
            return await task
        frames = _run(scenario())
        ids = [f.split("\n", 1)[0] for f in frames[1:]]
        assert ids == ["id: 1", "id: 2"]

    def test_heartbeat_and_counter_release(self, store, monkeypatch):
        monkeypatch.setattr(event_stream, "POLL_SECS", 0.01)
        monkeypatch.setattr(event_stream, "HEARTBEAT_SECS", 0.05)
        counter = {"n": 0}

        async def never():
            return False
        frames = _run(_collect(event_stream.stream(never, store, counter=counter), 2))
        assert frames[1] == ": heartbeat\n\n"
        assert counter["n"] == 0

    def test_stops_when_the_client_disconnects(self, store):
        calls = iter([False, True])

        async def disc():
            return next(calls)
        counter = {"n": 0}

        async def drain():
            return [f async for f in event_stream.stream(disc, store, counter=counter)]
        assert _run(drain()) == [f"retry: {event_stream.RETRY_MS}\n\n"] and counter["n"] == 0

    def test_last_event_id_parsing(self):
        assert event_stream.parse_last_event_id("12") == 12
        assert event_stream.parse_last_event_id("abc") is None and event_stream.parse_last_event_id("-3") is None
        assert event_stream.parse_last_event_id(None) is None


@pytest.fixture
def live(tmp_path, monkeypatch):
    monkeypatch.delenv("COGNIREPO_EVENTS", raising=False)
    built = ui_server.build(str(tmp_path), "127.0.0.1", 0)
    t = threading.Thread(target=built.server.run, kwargs={"sockets": [built.sock]}, daemon=True)
    t.start()
    for _ in range(100):
        if built.server.started:
            break
        time.sleep(0.05)
    assert built.server.started
    yield built, str(tmp_path)
    built.server.should_exit = True
    t.join(10)
    built.sock.close()
    assert not t.is_alive(), "server did not shut down with an open stream"


class TestEndpoint:
    def test_requires_auth_and_streams_over_real_http(self, live, monkeypatch):
        built, root = live
        base = f"http://127.0.0.1:{built.port}"
        assert httpx.get(base + "/api/v1/events").status_code == 401
        store = _store_dir(root)
        events.emit("tool.end", store_dir=store, tool="old")
        h = {"Authorization": f"Bearer {built.token}"}
        with httpx.stream("GET", base + "/api/v1/events?replay=5&types=tool.*", headers=h, timeout=10) as r:
            assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
            assert r.headers["cache-control"] == "no-store"
            lines = r.iter_lines()
            got = []
            threading.Timer(0.5, events.emit, args=("tool.end",), kwargs={"store_dir": store, "tool": "new"}).start()
            events.emit("watcher.reindex", store_dir=store)          # filtered out by types=tool.*
            for ln in lines:
                if ln.startswith("data: "):
                    got.append(json.loads(ln[6:])["tool"])
                if len(got) == 2:
                    break
        assert got == ["old", "new"]

    def test_stream_cap_returns_429(self, live):
        built, _ = live
        h = {"Authorization": f"Bearer {built.token}"}
        built.server.config.app.state.stream_counter["n"] = event_stream.MAX_STREAMS
        r = httpx.get(f"http://127.0.0.1:{built.port}/api/v1/events", headers=h)
        assert r.status_code == 429 and r.json() == {"error": "too_many_streams"}


class TestEmitters:
    def _events(self):
        from core.config.paths import get_cognirepo_dir
        return _lines(str(get_cognirepo_dir()))

    def test_traced_emits_start_end_with_duration_and_summary(self, isolated_cognirepo, monkeypatch):
        from interface.server import mcp_server
        monkeypatch.setattr(mcp_server, "_MCP_SESSION", {"session_id": "sess-1"})
        res = mcp_server._traced("lookup_symbol", lambda **kw: [1, 2], name="foo", api_key="SECRET")  # pylint: disable=protected-access
        assert res == [1, 2]
        start, end = self._events()
        assert (start["type"], end["type"]) == ("tool.start", "tool.end")
        assert start["tool"] == end["tool"] == "lookup_symbol" and start["session_id"] == "sess-1"
        assert start["trace_id"] == end["trace_id"] and "name=foo" in start["args_summary"]
        assert "SECRET" not in json.dumps(self._events())
        assert end["result_summary"] == "2 results" and isinstance(end["dur_ms"], int)

    def test_traced_emits_error_with_class_name_only(self, isolated_cognirepo):
        from interface.server import mcp_server

        def boom(**kw):
            raise ValueError("private user text")
        with pytest.raises(ValueError):
            mcp_server._traced("t", boom, query="q")        # pylint: disable=protected-access
        err = self._events()[-1]
        assert err["type"] == "tool.error" and err["error"] == "ValueError" and "private" not in json.dumps(err)

    def test_traced_shed_emits_event(self, isolated_cognirepo, monkeypatch):
        from interface.server import mcp_server
        from data.memory.circuit_breaker import CircuitOpenError

        class Open:
            def check(self):
                raise CircuitOpenError("over limit")
        monkeypatch.setattr(mcp_server, "get_breaker", lambda: Open())
        assert mcp_server._traced("t", lambda: 1)["shed"] is True    # pylint: disable=protected-access
        assert self._events()[-1]["type"] == "tool.shed" and self._events()[-1]["reason"] == "circuit_open"

    def test_a_failing_event_log_never_fails_the_tool(self, isolated_cognirepo, monkeypatch):
        from interface.server import mcp_server
        monkeypatch.setattr(events, "_emit", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
        assert mcp_server._traced("t", lambda: {"ok": 1}) == {"ok": 1}   # pylint: disable=protected-access

    def test_watcher_reindex_emits_only_when_something_happened(self, isolated_cognirepo):
        from intelligence.indexer.file_watcher import RepoFileHandler
        h = RepoFileHandler.__new__(RepoFileHandler)
        h.repo_root, h.session_id = str(isolated_cognirepo), "watch_1"
        from core.config.paths import get_cognirepo_dir
        h._write_last_watcher_reindex([], [])                       # pylint: disable=protected-access
        assert not os.path.exists(events.events_path(str(get_cognirepo_dir())))
        h._write_last_watcher_reindex(["a.py"], ["b.py"])           # pylint: disable=protected-access
        ev = self._events()[-1]
        assert ev["type"] == "watcher.reindex" and ev["reindexed"] == ["a.py"] and ev["removed"] == ["b.py"]


class TestShutdown:
    def test_an_open_stream_does_not_block_server_shutdown(self, tmp_path):
        built = ui_server.build(str(tmp_path), "127.0.0.1", 0)
        t = threading.Thread(target=built.server.run, kwargs={"sockets": [built.sock]}, daemon=True)
        t.start()
        for _ in range(100):
            if built.server.started:
                break
            time.sleep(0.05)
        opened = threading.Event()

        def hold():
            try:
                with httpx.stream("GET", f"http://127.0.0.1:{built.port}/api/v1/events",
                                  headers={"Authorization": f"Bearer {built.token}"}, timeout=30) as r:
                    opened.set()
                    for _ in r.iter_lines():
                        pass
            except httpx.HTTPError:
                pass
        c = threading.Thread(target=hold, daemon=True)
        c.start()
        assert opened.wait(10)
        t0 = time.monotonic()
        built.server.should_exit = True
        t.join(15)
        built.sock.close()
        assert not t.is_alive() and time.monotonic() - t0 < 10
