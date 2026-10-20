# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""#209 — graph_seq, graph.delta events and GET /api/v1/graph/changes."""
import pytest
from fastapi.testclient import TestClient

from core import events
from core.config.paths import get_cognirepo_dir
from data.graph import graph_seq
from data.graph.knowledge_graph import KnowledgeGraph
from interface.ui import graph_changes
from interface.ui import security as sec
from interface.ui.app import create_app
from interface.ui.audit import AuditLog

PORT = 8768
TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def store(isolated_cognirepo, monkeypatch):
    monkeypatch.delenv("COGNIREPO_EVENTS", raising=False)
    monkeypatch.delenv("COGNIREPO_EVENTS_METADATA_ONLY", raising=False)
    return str(get_cognirepo_dir())


def _deltas(store):
    return [e for e in events.read_since(store, 0, 10_000) if e["type"] == "graph.delta"]


class TestDeltaFor:
    @pytest.fixture
    def g(self):
        import networkx as nx
        g = nx.DiGraph()
        g.add_node("a", type="FILE")
        g.add_node("b", type="FILE")
        g.add_edge("a", "b", rel="IMPORTS")
        return g

    def test_ops(self, g):
        d = graph_seq.delta_for
        assert d(g, ("n", "c", "FUNCTION", {})) == {"op": "add_node", "id": "c", "kind": "FUNCTION"}
        assert d(g, ("n", "a", "FILE", {"x": 1})) == {"op": "update_node", "id": "a"}
        assert d(g, ("n", "a", "FILE", {})) is None                       # idempotent re-add: nothing changed
        assert d(g, ("e", "b", "a", "CALLS", 1.0, {})) == {"op": "add_edge", "src": "b", "dst": "a", "rel": "CALLS"}
        assert d(g, ("e", "a", "b", "IMPORTS", 1.0, {})) == {"op": "update_edge", "src": "a", "dst": "b"}
        assert d(g, ("rn", "a")) == {"op": "del_node", "id": "a"}
        assert d(g, ("rn", "zz")) is None
        assert d(g, ("re", "a", "b")) == {"op": "del_edge", "src": "a", "dst": "b"}
        assert d(g, ("re", "b", "a")) is None
        assert d(g, ("ga", "complete", True)) is None

    def test_conditional_remove_only_reports_real_deletions(self, g):
        assert graph_seq.delta_for(g, ("rnd", "a", 0)) is None           # still connected: not deleted
        assert graph_seq.delta_for(g, ("rnd", "a", 1)) == {"op": "del_node", "id": "a"}


class TestSeqAndEvents:
    def test_save_publishes_one_batch_and_bumps_once(self, store):
        kg = KnowledgeGraph()
        assert graph_seq.read(store) == 0
        kg.add_node("f1", "FILE")
        kg.add_node("fn1", "FUNCTION")
        kg.add_edge("f1", "fn1", "CONTAINS")
        assert graph_seq.read(store) == 0                  # nothing durable yet
        kg.save()
        assert graph_seq.read(store) == 1
        ev = _deltas(store)
        assert len(ev) == 1 and ev[0]["graph_seq"] == 1 and ev[0]["op_count"] == 3
        assert [o["op"] for o in ev[0]["ops"]] == ["add_node", "add_node", "add_edge"]
        kg.save()                                           # nothing changed: no bump, no event
        assert graph_seq.read(store) == 1 and len(_deltas(store)) == 1

    def test_seq_survives_compaction_and_reload(self, store):
        kg = KnowledgeGraph()
        kg.add_node("a", "FILE")
        kg.save()
        kg.add_node("b", "FILE")
        kg.save()                                           # save() compacts the journal
        assert graph_seq.read(store) == 2
        again = KnowledgeGraph()
        again.add_node("c", "FILE")
        again.save()
        assert graph_seq.read(store) == 3

    def test_journaled_flush_publishes_per_flush_not_again_at_save(self, store):
        kg = KnowledgeGraph()
        kg.begin_journal()
        kg.add_node("a", "FILE")
        kg.flush_journal()
        assert graph_seq.read(store) == 1
        kg.add_node("b", "FILE")
        kg.end_journal()
        assert graph_seq.read(store) == 2
        kg.save()
        assert graph_seq.read(store) == 2                  # already published at flush
        assert [e["graph_seq"] for e in _deltas(store)] == [1, 2]

    def test_bulk_batch_is_published_as_reset(self, store):
        kg = KnowledgeGraph()
        for i in range(graph_seq.MAX_BATCH_OPS + 5):
            kg.add_node(f"n{i}", "FILE")
        kg.save()
        ev = _deltas(store)[0]
        assert ev["reset"] is True and ev["op_count"] == graph_seq.MAX_BATCH_OPS + 5 and "ops" not in ev

    def test_metadata_only_never_writes_node_ids(self, store, monkeypatch):
        monkeypatch.setenv("COGNIREPO_EVENTS_METADATA_ONLY", "1")
        kg = KnowledgeGraph()
        kg.add_node("secret_symbol", "FUNCTION")
        kg.save()
        ev = _deltas(store)[0]
        assert ev["reset"] is True and "secret_symbol" not in open(events.events_path(store)).read()

    def test_publishing_never_breaks_a_save(self, store, monkeypatch):
        monkeypatch.setattr(events, "emit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        kg = KnowledgeGraph()
        kg.add_node("a", "FILE")
        kg.save()                                           # must not raise
        assert KnowledgeGraph().G.has_node("a")


class TestChangesFeed:
    def test_no_change_and_future_since(self, store):
        assert graph_changes.changes(store, 0, 500) == {"seq": 0, "ops": [], "reset": False, "more": False}
        assert graph_changes.changes(store, 7, 500)["reset"] is True

    def test_returns_ops_in_order_then_continues_from_seq(self, store):
        kg = KnowledgeGraph()
        kg.add_node("a", "FILE")
        kg.save()
        kg.add_node("b", "FILE")
        kg.add_edge("a", "b", "IMPORTS")
        kg.save()
        r = graph_changes.changes(store, 0, 500)
        assert r["reset"] is False and r["seq"] == 2 and r["more"] is False
        assert [o["op"] for o in r["ops"]] == ["add_node", "add_node", "add_edge"]
        r2 = graph_changes.changes(store, 1, 500)
        assert [o["id"] for o in r2["ops"] if o["op"] == "add_node"] == ["b"]
        assert graph_changes.changes(store, 2, 500)["ops"] == []

    def test_limit_pages_by_whole_batches(self, store):
        kg = KnowledgeGraph()
        for i in range(3):
            kg.add_node(f"a{i}", "FILE")
            kg.add_node(f"b{i}", "FILE")
            kg.save()
        r = graph_changes.changes(store, 0, 3)
        assert r["more"] is True and r["seq"] == 1 and len(r["ops"]) == 2
        r = graph_changes.changes(store, r["seq"], 100)
        assert r["more"] is False and r["seq"] == 3 and len(r["ops"]) == 4

    def test_a_missing_event_forces_reset(self, store, monkeypatch):
        kg = KnowledgeGraph()
        kg.add_node("a", "FILE")
        kg.save()
        monkeypatch.setenv("COGNIREPO_EVENTS", "0")        # batch 2 is counted but its event is not written
        kg.add_node("b", "FILE")
        kg.save()
        assert graph_seq.read(store) == 2
        r = graph_changes.changes(store, 0, 500)
        assert r["reset"] is True and r["ops"] == [] and r["seq"] == 2
        assert graph_changes.changes(store, 1, 500)["reset"] is True

    def test_bulk_batch_in_range_forces_reset(self, store):
        kg = KnowledgeGraph()
        for i in range(graph_seq.MAX_BATCH_OPS + 1):
            kg.add_node(f"n{i}", "FILE")
        kg.save()
        assert graph_changes.changes(store, 0, 500)["reset"] is True

    def test_far_behind_client_resets(self, store, monkeypatch):
        monkeypatch.setattr(graph_changes, "MAX_SPAN", 1)
        kg = KnowledgeGraph()
        for n in ("a", "b"):
            kg.add_node(n, "FILE")
            kg.save()
        assert graph_changes.changes(store, 0, 500)["reset"] is True


@pytest.fixture
def client(isolated_cognirepo, monkeypatch):
    monkeypatch.delenv("COGNIREPO_EVENTS", raising=False)
    cfg = sec.SecurityConfig(token=TOKEN, port=PORT, limiter=sec.AttemptLimiter(max_failures=3, base_lockout=60))
    app = create_app(cfg, str(isolated_cognirepo), AuditLog(str(isolated_cognirepo / "ui" / "audit.log")))
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as c:
        yield c


class TestApi:
    def test_requires_token(self, client):
        assert client.get("/api/v1/graph/changes").status_code == 401

    def test_changes_and_status_graph_seq(self, client):
        assert client.get("/api/v1/status", headers=AUTH).json()["indexer"]["graph_seq"] == 0
        kg = KnowledgeGraph()
        kg.add_node("a.py", "FILE")
        kg.add_edge("a.py", "a.py", "SELF")
        kg.save()
        assert client.get("/api/v1/status", headers=AUTH).json()["indexer"]["graph_seq"] == 1
        r = client.get("/api/v1/graph/changes?since=0", headers=AUTH).json()
        assert r == {"seq": 1, "reset": False, "more": False,
                     "ops": [{"op": "add_node", "id": "a.py", "kind": "FILE"},
                             {"op": "add_edge", "src": "a.py", "dst": "a.py", "rel": "SELF"}]}

    def test_validation(self, client):
        assert client.get("/api/v1/graph/changes?since=-1", headers=AUTH).status_code == 422
        assert client.get("/api/v1/graph/changes?limit=0", headers=AUTH).status_code == 422
        assert client.get("/api/v1/graph/changes?limit=5000", headers=AUTH).status_code == 422
