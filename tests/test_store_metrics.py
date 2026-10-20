# pylint: disable=missing-docstring, protected-access, redefined-outer-name, unused-argument
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""tests/test_store_metrics.py — store-derived /metrics, processes, audit tail, store sizes (#212)."""
import json
import os
import subprocess
import sys
import threading
import urllib.request
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from core import events
from core.metrics import metrics_available
from core.store_stats import dir_bytes, store_sizes
from data.graph import graph_seq
from interface.cli.metrics_server import create_metrics_server
from interface.ui import processes
from interface.ui import security as sec
from interface.ui.app import create_app
from interface.ui.audit import AuditLog
from interface.ui.status import indexer_status

pytestmark = pytest.mark.skipif(not metrics_available(), reason="prometheus_client not installed")
TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PORT = 8765


@pytest.fixture
def store(tmp_path):
    s = tmp_path / ".cognirepo"
    s.mkdir(exist_ok=True)
    return str(s)


def scrape(tmp_path, collect_twice=False):
    server = create_metrics_server("127.0.0.1", 0, str(tmp_path))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/metrics"
    try:
        body = urllib.request.urlopen(url).read().decode()
        if collect_twice:
            body = urllib.request.urlopen(url).read().decode()
        return body
    finally:
        server.shutdown()
        server.server_close()


def value(body, name, **labels):
    for line in body.splitlines():
        if line.startswith(name + "{") or line.startswith(name + " "):
            if all(f'{k}="{v}"' in line for k, v in labels.items()):
                return float(line.rsplit(" ", 1)[1])
    return None


def emit_calls(store):
    events.emit("tool.start", store_dir=store, tool="lookup_symbol", trace_id="a", session_id="s1")
    events.emit("tool.end", store_dir=store, tool="lookup_symbol", trace_id="a", session_id="s1", dur_ms=40)
    events.emit("tool.end", store_dir=store, tool="lookup_symbol", trace_id="b", session_id="s1", dur_ms=7000)
    events.emit("tool.error", store_dir=store, tool="store_memory", trace_id="c", session_id="s1", dur_ms=15000,
                error="StoreBusy", retryable=True)
    events.emit("tool.error", store_dir=store, tool="store_memory", trace_id="d", session_id="s1", dur_ms=3,
                error="ValueError")
    events.emit("tool.shed", store_dir=store, tool="context_pack", reason="circuit_open", session_id="s1")


class TestToolCallMetrics:
    def test_counts_by_tool_and_outcome(self, tmp_path, store):
        emit_calls(store)
        body = scrape(tmp_path)
        repo = os.path.basename(str(tmp_path))
        assert value(body, "cognirepo_tool_calls_total", repo=repo, tool="lookup_symbol", outcome="ok") == 2
        assert value(body, "cognirepo_tool_calls_total", tool="store_memory", outcome="busy") == 1
        assert value(body, "cognirepo_tool_calls_total", tool="store_memory", outcome="error") == 1
        assert value(body, "cognirepo_tool_calls_total", tool="context_pack", outcome="shed") == 1
        assert value(body, "cognirepo_store_busy_total", repo=repo) == 1

    def test_histogram_buckets_are_cumulative(self, tmp_path, store):
        emit_calls(store)
        body = scrape(tmp_path)
        assert value(body, "cognirepo_tool_call_duration_seconds_bucket", tool="lookup_symbol", le="0.05") == 1
        assert value(body, "cognirepo_tool_call_duration_seconds_bucket", tool="lookup_symbol", le="10.0") == 2
        assert value(body, "cognirepo_tool_call_duration_seconds_count", tool="lookup_symbol") == 2
        assert value(body, "cognirepo_tool_call_duration_seconds_sum", tool="lookup_symbol") == pytest.approx(7.04)
        # a shed call never ran, so it has no duration
        assert value(body, "cognirepo_tool_call_duration_seconds_count", tool="context_pack") is None

    def test_counters_accumulate_across_scrapes_without_double_counting(self, tmp_path, store):
        server = create_metrics_server("127.0.0.1", 0, str(tmp_path))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_address[1]}/metrics"
        try:
            emit_calls(store)
            first = urllib.request.urlopen(url).read().decode()
            again = urllib.request.urlopen(url).read().decode()
            assert value(first, "cognirepo_tool_calls_total", tool="lookup_symbol", outcome="ok") == 2
            assert value(again, "cognirepo_tool_calls_total", tool="lookup_symbol", outcome="ok") == 2
            events.emit("tool.end", store_dir=store, tool="lookup_symbol", dur_ms=1)
            third = urllib.request.urlopen(url).read().decode()
            assert value(third, "cognirepo_tool_calls_total", tool="lookup_symbol", outcome="ok") == 3
        finally:
            server.shutdown()
            server.server_close()

    def test_events_from_another_process_are_seen(self, tmp_path, store):
        """The point of #212: the numbers come from the store, not from this process's memory."""
        code = ("from core import events; import sys; "
                "events.emit('tool.end', store_dir=sys.argv[1], tool='other_proc', dur_ms=5)")
        subprocess.run([sys.executable, "-c", code, store], check=True, cwd=os.getcwd())
        assert value(scrape(tmp_path), "cognirepo_tool_calls_total", tool="other_proc", outcome="ok") == 1

    def test_no_events_is_a_valid_scrape(self, tmp_path, store):
        body = scrape(tmp_path)
        assert "cognirepo_graph_seq" in body and value(body, "cognirepo_store_busy_total") == 0


class TestStoreGauges:
    def test_graph_index_and_sizes(self, tmp_path, store):
        (tmp_path / ".cognirepo" / "graph").mkdir(exist_ok=True)
        (tmp_path / ".cognirepo" / "graph" / "graph.seq").write_text("7")
        graph_seq.write_stats(store, 120, 340)
        (tmp_path / ".cognirepo" / "index").mkdir(exist_ok=True)
        (tmp_path / ".cognirepo" / "index" / "manifest.json").write_text(json.dumps(
            {"indexed_at": datetime.now(timezone.utc).isoformat(), "source_file_count": 12, "symbol_count": 99}))
        body = scrape(tmp_path)
        assert value(body, "cognirepo_graph_seq") == 7
        assert value(body, "cognirepo_graph_nodes") == 120 and value(body, "cognirepo_graph_edges") == 340
        assert value(body, "cognirepo_index_files") == 12 and value(body, "cognirepo_index_symbols") == 99
        assert 0 <= value(body, "cognirepo_index_age_seconds") < 60
        assert value(body, "cognirepo_store_bytes", part="graph") > 0
        assert value(body, "cognirepo_store_bytes", part="total") >= value(body, "cognirepo_store_bytes", part="graph")
        assert value(body, "cognirepo_watcher_up") == 0
        assert "cognirepo_watcher_heartbeat_age_seconds" not in body

    def test_graph_stats_written_by_a_real_save(self, tmp_path, store):
        from data.graph.knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph()
        kg.add_node("a", "FILE")
        kg.add_node("b", "FILE")
        kg.add_edge("a", "b", "IMPORTS")
        kg.save()
        assert graph_seq.read_stats(store) == {"nodes": 2, "edges": 1}

    def test_missing_manifest_and_stats_are_omitted_not_zero(self, tmp_path, store):
        body = scrape(tmp_path)
        assert "cognirepo_graph_nodes" not in body and "cognirepo_index_age_seconds" not in body

    def test_legacy_in_process_counters_are_not_served(self, tmp_path, store):
        assert "cognirepo_memory_ops_total" not in scrape(tmp_path)


class TestStoreSizes:
    def test_sizes_and_cache(self, tmp_path):
        s = tmp_path / "st"
        (s / "a").mkdir(parents=True)
        (s / "a" / "f").write_bytes(b"x" * 10)
        (s / "cfg").write_bytes(b"y" * 5)
        sizes = store_sizes(str(s))
        assert sizes == {"a": 10, "_files": 5, "total": 15}
        (s / "a" / "g").write_bytes(b"z" * 100)
        assert store_sizes(str(s))["a"] == 10                      # cached
        assert store_sizes(str(s), ttl=0)["a"] == 110

    def test_symlinks_are_not_followed(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "big").write_bytes(b"x" * 1000)
        s = tmp_path / "st2"
        s.mkdir()
        os.symlink(outside, s / "link")
        assert dir_bytes(str(s)) == 0 and store_sizes(str(s), ttl=0) == {"total": 0}

    def test_missing_store(self, tmp_path):
        assert store_sizes(str(tmp_path / "nope"), ttl=0) == {"total": 0}


@pytest.fixture
def client(tmp_path, store):
    cfg = sec.SecurityConfig(token=TOKEN, port=PORT, limiter=sec.AttemptLimiter(max_failures=3, base_lockout=60))
    audit = AuditLog(str(tmp_path / "ui" / "audit.log"))
    with TestClient(create_app(cfg, str(tmp_path), audit), base_url=f"http://127.0.0.1:{PORT}") as c:
        c.audit = audit
        yield c


class TestStatusStoreBytes:
    def test_indexer_status_has_store_bytes(self, tmp_path, store):
        os.makedirs(os.path.join(store, "graph"), exist_ok=True)
        open(os.path.join(store, "graph", "x"), "wb").write(b"1234")
        st = indexer_status(str(tmp_path))
        assert st["store_bytes"]["graph"] == 4 and st["store_bytes"]["total"] >= 4

    def test_in_status_response(self, client):
        assert "total" in client.get("/api/v1/status", headers=AUTH).json()["indexer"]["store_bytes"]


class TestAuditEndpoint:
    def test_requires_token(self, client):
        assert client.get("/api/v1/audit").status_code == 401

    def test_returns_tail_in_order_and_bounds(self, client):
        for i in range(5):
            client.audit.log("probe", n=i)
        rows = client.get("/api/v1/audit?tail=3", headers=AUTH).json()
        assert [r["n"] for r in rows if r.get("event") == "probe" or "n" in r][-3:] == [2, 3, 4]
        assert client.get("/api/v1/audit?tail=0", headers=AUTH).status_code == 422
        assert client.get("/api/v1/audit?tail=501", headers=AUTH).status_code == 422

    def test_never_contains_the_token(self, client):
        client.get("/api/v1/status", headers=AUTH)
        assert TOKEN not in client.get("/api/v1/audit", headers=AUTH).text


class TestProcesses:
    def test_requires_token(self, client):
        assert client.get("/api/v1/processes").status_code == 401

    def test_lists_ui_with_real_usage(self, client):
        rows = client.get("/api/v1/processes", headers=AUTH).json()
        ui = next(r for r in rows if r["role"] == "ui")
        assert ui["pid"] == os.getpid() and ui["rss_bytes"] > 0 and ui["threads"] >= 1

    def test_live_mcp_session_listed_dead_and_closed_not(self, tmp_path, store):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        events.emit("session.start", store_dir=store, session_id="live", client="claude-code", pid=os.getpid())
        events.emit("session.start", store_dir=store, session_id="gone", client="x", pid=dead.pid)
        events.emit("session.start", store_dir=store, session_id="done", client="y", pid=os.getpid() + 0)
        events.emit("session.end", store_dir=store, session_id="done", client="y")
        rows = processes.list_processes(str(tmp_path), store)
        mcp = [r for r in rows if r["role"] == "mcp"]
        assert [(r["session_id"], r["detail"]) for r in mcp] == [("live", "claude-code")]
        assert mcp[0]["rss_bytes"] > 0

    def test_watcher_row_from_registry(self, tmp_path, store, monkeypatch):
        from interface.ui import repos
        monkeypatch.setattr(repos, "watcher_state", lambda root, st: {
            "state": "running", "pid": os.getpid(), "heartbeat_age_s": 3.5, "last_reindex": None})
        w = next(r for r in processes.list_processes(str(tmp_path), store) if r["role"] == "watcher")
        assert w["heartbeat_age_s"] == 3.5 and w["state"] == "running"

    def test_uninspectable_pid_gives_nulls_not_an_error(self):
        assert processes._usage(2**22 + 12345) == {"rss_bytes": None, "threads": None}

    def test_session_rows_carry_pid(self, store):
        events.emit("session.start", store_dir=store, session_id="p", pid=4242)
        assert events.list_sessions(store)[0]["pid"] == 4242


class TestCheckpoint:
    def state_path(self, store):
        return os.path.join(store, "metrics", "state.json")

    def test_restart_resumes_counters_without_double_counting(self, tmp_path, store):
        emit_calls(store)
        first = scrape(tmp_path)
        assert os.path.isfile(self.state_path(store))
        events.emit("tool.end", store_dir=store, tool="lookup_symbol", dur_ms=2)
        second = scrape(tmp_path)                                  # a brand-new metrics server
        assert value(first, "cognirepo_tool_calls_total", tool="lookup_symbol", outcome="ok") == 2
        assert value(second, "cognirepo_tool_calls_total", tool="lookup_symbol", outcome="ok") == 3
        assert value(second, "cognirepo_store_busy_total") == 1
        assert value(second, "cognirepo_events_missed_total") == 0

    def test_counts_survive_the_log_being_rotated_away(self, tmp_path, store):
        emit_calls(store)
        scrape(tmp_path)
        edir = events.events_dir(store)
        for name in os.listdir(edir):
            if name.startswith("events.jsonl"):
                os.remove(os.path.join(edir, name))               # retention lost everything
        events.emit("tool.end", store_dir=store, tool="lookup_symbol", dur_ms=2)
        body = scrape(tmp_path)
        assert value(body, "cognirepo_tool_calls_total", tool="lookup_symbol", outcome="ok") == 3

    def test_events_lost_to_rotation_are_counted_not_hidden(self, tmp_path, store):
        emit_calls(store)                                          # seq 1..6
        scrape(tmp_path)
        for i in range(3):                                         # seq 7..9 written, then 7..8 rotate away
            events.emit("tool.end", store_dir=store, tool="x", dur_ms=1)
        path = events.events_path(store)
        lines = open(path, encoding="utf-8").read().splitlines()
        open(path, "w", encoding="utf-8").write("\n".join(lines[-1:]) + "\n")
        body = scrape(tmp_path)
        assert value(body, "cognirepo_events_missed_total") == 2

    def test_recreated_store_discards_stale_tallies(self, tmp_path, store):
        emit_calls(store)
        scrape(tmp_path)
        edir = events.events_dir(store)
        for name in os.listdir(edir):
            os.remove(os.path.join(edir, name))                   # store wiped, checkpoint left behind
        events.emit("tool.end", store_dir=store, tool="fresh", dur_ms=1)
        body = scrape(tmp_path)
        assert value(body, "cognirepo_tool_calls_total", tool="lookup_symbol", outcome="ok") is None
        assert value(body, "cognirepo_tool_calls_total", tool="fresh", outcome="ok") == 1

    @pytest.mark.parametrize("junk", ["{not json", '{"version": 99}', '{"version": 1, "seq": "x"}', "[]"])
    def test_corrupt_checkpoint_starts_fresh(self, tmp_path, store, junk):
        emit_calls(store)
        os.makedirs(os.path.dirname(self.state_path(store)), exist_ok=True)
        open(self.state_path(store), "w", encoding="utf-8").write(junk)
        body = scrape(tmp_path)
        assert value(body, "cognirepo_tool_calls_total", tool="lookup_symbol", outcome="ok") == 2

    def test_no_checkpoint_write_when_nothing_changed(self, tmp_path, store):
        emit_calls(store)
        scrape(tmp_path)
        stamp = os.stat(self.state_path(store)).st_mtime_ns
        scrape(tmp_path)
        assert os.stat(self.state_path(store)).st_mtime_ns == stamp


class TestEventLogAgeAndVectors:
    def test_log_age_present_only_with_events(self, tmp_path, store):
        assert "cognirepo_event_log_age_seconds" not in scrape(tmp_path)
        events.emit("tool.end", store_dir=store, tool="t", dur_ms=1)
        assert 0 <= value(scrape(tmp_path), "cognirepo_event_log_age_seconds") < 60

    def test_vector_count_from_manifest(self, tmp_path, store):
        os.makedirs(os.path.join(store, "index"), exist_ok=True)
        open(os.path.join(store, "index", "manifest.json"), "w", encoding="utf-8").write(
            json.dumps({"vector_count": 41, "symbol_count": 40}))
        assert value(scrape(tmp_path), "cognirepo_index_vectors") == 41

    def test_real_index_save_records_vector_count(self, tmp_path, store):
        from data.graph.knowledge_graph import KnowledgeGraph
        from intelligence.indexer.ast_indexer import ASTIndexer
        src = tmp_path / "m.py"
        src.write_text("def f():\n    return 1\n")
        idx = ASTIndexer(graph=KnowledgeGraph())
        idx._embed_enabled = False
        idx.index_file("m.py", str(src))
        idx.save()
        man = json.loads(open(os.path.join(store, "index", "manifest.json"), encoding="utf-8").read())
        assert isinstance(man["vector_count"], int) and man["vector_count"] >= 0


class TestPrometheusFormat:
    def test_scrape_parses_and_histograms_are_consistent(self, tmp_path, store):
        from prometheus_client.parser import text_string_to_metric_families
        emit_calls(store)
        fams = {f.name: f for f in text_string_to_metric_families(scrape(tmp_path))}
        assert fams["cognirepo_tool_calls"].type == "counter"
        assert fams["cognirepo_tool_call_duration_seconds"].type == "histogram"
        hist = fams["cognirepo_tool_call_duration_seconds"].samples
        for tool in ("lookup_symbol", "store_memory"):
            buckets = [s for s in hist if s.name.endswith("_bucket") and s.labels["tool"] == tool]
            counts = [s.value for s in buckets]
            assert counts == sorted(counts), "buckets must be cumulative"
            total = next(s.value for s in hist if s.name.endswith("_count") and s.labels["tool"] == tool)
            assert buckets[-1].labels["le"] == "+Inf" and buckets[-1].value == total

    def test_promtool_accepts_the_output_when_installed(self, tmp_path, store):
        import shutil
        if shutil.which("promtool") is None:
            pytest.skip("promtool not installed")
        emit_calls(store)
        out = subprocess.run(["promtool", "check", "metrics"], input=scrape(tmp_path), text=True,
                             capture_output=True, check=False)
        assert out.returncode == 0, out.stderr


class TestRealToolWrapper:
    def test_traced_calls_show_up_in_the_scrape(self, tmp_path, store, monkeypatch):
        mcp_server = pytest.importorskip("interface.server.mcp_server")
        from core.config.lock import LockTimeout

        def ok():
            return {"ok": True}

        def boom():
            raise ValueError("x")

        def busy():
            raise LockTimeout("lock")

        mcp_server._traced("ok_tool", ok)
        mcp_server._traced("ok_tool", ok)
        with pytest.raises(ValueError):          # unexpected errors are re-raised after being recorded
            mcp_server._traced("boom_tool", boom)
        mcp_server._traced("busy_tool", busy)
        body = scrape(tmp_path)
        assert value(body, "cognirepo_tool_calls_total", tool="ok_tool", outcome="ok") == 2
        assert value(body, "cognirepo_tool_calls_total", tool="boom_tool", outcome="error") == 1
        assert value(body, "cognirepo_tool_calls_total", tool="busy_tool", outcome="busy") == 1
        assert value(body, "cognirepo_store_busy_total") == 1
        assert value(body, "cognirepo_tool_call_duration_seconds_count", tool="ok_tool") == 2


class TestProcessScan:
    def make_serve(self, cwd):
        script = os.path.join(cwd, "cognirepo")
        open(script, "w", encoding="utf-8").write("import time\ntime.sleep(60)\n")
        return subprocess.Popen([sys.executable, script, "serve"], cwd=cwd)

    def test_finds_serve_processes_by_cwd_only(self, tmp_path, store):
        mine, other = tmp_path / "a", tmp_path / "b"
        mine.mkdir()
        other.mkdir()
        p1, p2 = self.make_serve(str(mine)), self.make_serve(str(other))
        try:
            import time
            time.sleep(0.4)
            processes._scan_cache.clear()
            assert processes.discover_serve_pids(str(mine)) == [p1.pid]
            rows = processes.list_processes(str(mine), store)
            assert [r["pid"] for r in rows if r["role"] == "mcp"] == [p1.pid]
            assert next(r for r in rows if r["pid"] == p1.pid)["rss_bytes"] > 0
        finally:
            p1.kill()
            p2.kill()

    def test_event_row_and_scan_do_not_duplicate(self, tmp_path, store):
        proc = self.make_serve(str(tmp_path))
        try:
            import time
            time.sleep(0.4)
            processes._scan_cache.clear()
            events.emit("session.start", store_dir=store, session_id="s", client="claude-code", pid=proc.pid)
            mcp = [r for r in processes.list_processes(str(tmp_path), store) if r["role"] == "mcp"]
            assert len(mcp) == 1 and mcp[0]["detail"] == "claude-code"
        finally:
            proc.kill()

    def test_scan_is_cached(self, tmp_path, monkeypatch):
        processes._scan_cache.clear()
        processes.discover_serve_pids(str(tmp_path))
        monkeypatch.setattr("psutil.process_iter", lambda *a, **k: pytest.fail("should be cached"))
        assert processes.discover_serve_pids(str(tmp_path)) == []

    def test_is_serve_matching(self):
        assert processes._is_serve(["/usr/bin/python", "/home/u/.local/bin/cognirepo", "serve"])
        assert processes._is_serve(["python", "-m", "interface.cli.main", "serve", "--x"])
        assert not processes._is_serve(["python", "-m", "interface.cli.main", "ui", "--serve"])
        assert not processes._is_serve(["vim", "serve"])
