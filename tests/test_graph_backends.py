# Copyright (c) 2026 Ashlesh T. — AGPL-3.0 (see LICENSE)
"""Graph storage backends (#115, ADR 002): networkx and SQLite must answer identically.

The conformance class runs one scenario through the public ``KnowledgeGraph`` surface on both
backends and compares every read. The rest covers what is specific to SQLite: backend selection,
the pickle importer, durability across processes, the writer lease, and the change feed.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import pathlib
import subprocess
import sys
import textwrap
import time

import pytest

from core.config.paths import get_cognirepo_dir, set_cognirepo_dir
from data.graph import backend as gb
from data.graph import graph_seq
from data.graph import sqlite_graph as sg
from data.graph.journal import JournalBusy
from data.graph.knowledge_graph import EdgeType, KnowledgeGraph, NodeType
from data.graph.sqlite_graph import SqliteGraph

_REPO = pathlib.Path(__file__).resolve().parent.parent
BACKENDS = ["networkx", "sqlite"]


def _store() -> pathlib.Path:
    return pathlib.Path(get_cognirepo_dir())


def _fresh_store(tmp_path: pathlib.Path, name: str) -> None:
    """A separate, empty store per backend, so one cannot import the other's graph."""
    root = tmp_path / name / ".cognirepo"
    (root / "graph").mkdir(parents=True)
    set_cognirepo_dir(str(root))


@pytest.fixture
def use(monkeypatch):
    """Select a backend for the next ``KnowledgeGraph()``."""
    def _use(name: str) -> None:
        monkeypatch.setenv(gb.ENV_VAR, name)
    return _use


def build(g: KnowledgeGraph) -> None:
    """A scenario touching every primitive op and the awkward corners of networkx semantics."""
    g.add_node("a.py", NodeType.FILE)
    g.add_node("b.py", NodeType.FILE)
    g.add_node("a.py::f", NodeType.FUNCTION, file="a.py", line=1, tags=["x", "y"])
    g.add_node("a.py::g", NodeType.FUNCTION, file="a.py", line=9)
    g.add_node("b.py::h", NodeType.FUNCTION, file="b.py", line=2)
    g.add_node("b.py::K", NodeType.CLASS, file="b.py")
    g.add_node("concept::len", NodeType.CONCEPT)
    g.add_node("concept::retry", NodeType.CONCEPT)
    g.add_node("symbol::gone", NodeType.CONCEPT, unresolved=True)
    g.add_node("lonely", NodeType.CONCEPT)
    g.add_edge("a.py::f", "a.py", EdgeType.DEFINED_IN)
    g.add_edge("a.py::g", "a.py", EdgeType.DEFINED_IN)
    g.add_edge("b.py::h", "b.py", EdgeType.DEFINED_IN)
    g.add_edge("b.py::K", "b.py", EdgeType.DEFINED_IN)
    g.add_edge("a.py::f", "a.py::g", EdgeType.CALLED_BY, purpose="orchestrates", weight=2.5)
    g.add_edge("a.py::g", "a.py::f", EdgeType.CALLS)
    g.add_edge("b.py::h", "a.py::f", EdgeType.CALLED_BY)
    g.add_edge("a.py::f", "a.py::f", EdgeType.RELATES_TO)                    # self loop
    g.add_edge("a.py::f", "concept::len", EdgeType.RELATES_TO)
    g.add_edge("b.py::h", "symbol::gone", EdgeType.CALLED_BY)
    g.add_edge("b.py::K", "a.py::g", EdgeType.INHERITS)
    g.add_edge("a.py::f", "never-declared", EdgeType.RELATES_TO)             # networkx creates the endpoint
    g.add_edge("a.py::f", "a.py::g", EdgeType.CALLED_BY, weight=4.0, hits=3)  # update existing edge
    g.add_node("a.py::f", NodeType.CLASS, line=2)                           # existing node: attrs merge, type kept
    g.set_node_attrs("b.py::h", doc="x")
    g.set_node_attrs("ghost", doc="ignored")
    g.set_edge_attrs("b.py::h", "a.py::f", note="n")
    g.set_edge_attrs("ghost", "nowhere", note="ignored")
    g.remove_edge("a.py::g", "a.py::f")
    g.remove_edge("x", "y")
    g.remove_node("concept::retry")
    g.remove_node_if_degree_at_most("lonely", 0)
    g.remove_node_if_degree_at_most("a.py", 0)                              # still connected: kept
    g.mark_complete()


def snapshot(g: KnowledgeGraph, repo_root: str) -> dict:
    ids = g.node_ids()
    out: dict = {
        "counts": (g.node_count(), g.edge_count(), g.stats()),
        "node_ids": ids,
        "nodes": g.nodes_with_data(),
        "edges": g.edges_with_data(),
        "in_degrees": g.in_degrees(),
        "complete": g.graph_attr("complete"),
        "unset_attr": g.graph_attr("nope", "dflt"),
        "files": g.count_nodes_of_type(NodeType.FILE),
        "isolated": g.isolated_node_ids(),
        "top": g.top_degree_ids(4),
        "stubs": g.orphan_stubs(),
        "a_nodes": g.nodes_for_file("a.py"),
        "base": g.incremental_base_status(2),
        "per_node": {},
    }
    for n in [*ids, "missing"]:
        out["per_node"][n] = {
            "exists": g.node_exists(n), "attrs": g.node_attrs(n), "succ": g.successors(n),
            "pred": g.predecessors(n), "degree": g.degree(n),
            "nb2": g.get_neighbours(n, depth=2), "nb_rel": g.get_neighbours(n, depth=3, edge_type="CALLED_BY"),
            "edges": {m: (g.has_edge(n, m), g.edge_data(n, m)) for m in [*ids, "missing"]},
        }
    view = g.undirected_snapshot()
    pairs = [(a, b) for a in ids[:6] for b in [*ids[:6], "missing"]]
    out["paths"] = {
        f"{a}->{b}": (g.hop_distance(a, b), g.shortest_path(a, b), g.path_between(a, b),
                      g.path_between(a, b, undirected=True), view.hops(a, b))
        for a, b in pairs
    }
    sub = g.subgraph_around("a.py::f", radius=2)
    out["sub"] = {"nodes": sorted(sub["nodes"], key=lambda d: d["node_id"]),
                  "edges": sorted(sub["edges"], key=lambda d: (d["src"], d["dst"])),
                  "truncated": sub.get("truncated")}
    small = g.subgraph_around("a.py::f", radius=3, max_nodes=3)
    out["sub_small"] = (len(small["nodes"]), small.get("truncated"))
    out["sub_missing"] = g.subgraph_around("missing")
    rep = g.integrity_report(repo_root)
    rep.pop("swept_at")
    out["integrity"] = {k: sorted(v) for k, v in rep.items()}
    return out


class TestConformance:
    def test_both_backends_answer_identically(self, use, tmp_path):
        snaps = {}
        for name in BACKENDS:
            _fresh_store(tmp_path, name)
            use(name)
            g = KnowledgeGraph()
            assert type(g).__name__ == ("SqliteGraph" if name == "sqlite" else "KnowledgeGraph")
            build(g)
            g.save()
            snaps[name] = snapshot(g, str(tmp_path))
            if name == "sqlite":
                g.close()
            snaps[name + "-reopened"] = snapshot(KnowledgeGraph(), str(tmp_path))   # what another process sees
        assert snaps["sqlite"] == snaps["networkx"]
        assert snaps["sqlite-reopened"] == snaps["networkx-reopened"] == snaps["networkx"]

    def test_remove_file_nodes_keeps_callers_on_a_stub(self, use, tmp_path):
        results = {}
        for name in BACKENDS:
            _fresh_store(tmp_path, name)
            use(name)
            g = KnowledgeGraph()
            build(g)
            removed = g.remove_file_nodes("a.py")
            results[name] = (sorted(removed), g.node_ids(), g.edges_with_data(), g.orphan_stubs())
        assert results["sqlite"] == results["networkx"]
        assert "symbol::f" in results["sqlite"][1]          # b.py::h still calls f -> stub

    def test_attribute_values_round_trip_as_json(self, use):
        use("sqlite")
        g = KnowledgeGraph()
        g.add_node("n", NodeType.CONCEPT, pair=(1, 2), tags={"b", "a"}, nested={"k": [1, None, True]}, f=1.5)
        g.save()
        assert g.node_attrs("n") == {"type": "CONCEPT", "pair": [1, 2], "tags": ["a", "b"],
                                     "nested": {"k": [1, None, True]}, "f": 1.5}

    def test_no_in_memory_graph_on_sqlite(self, use):
        use("sqlite")
        with pytest.raises(AttributeError, match="no in-memory networkx graph"):
            _ = KnowledgeGraph().G


def _methods_touching_G(cls: type) -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(cls)))
    return {fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
            and any(isinstance(n, ast.Attribute) and n.attr == "G" and isinstance(n.value, ast.Name)
                    and n.value.id == "self" for n in ast.walk(fn))}


class TestEveryNetworkxPathIsOverridden:
    #: pickle-persistence internals, reachable only through entry points SqliteGraph replaces
    #: (save, _load/load, reload_if_changed, begin_journal, ...)
    PICKLE_ONLY = {"_load_base", "_rebase", "_try_incremental_replay", "_replay_journal", "_do", "_apply",
                   "__init__"}

    def test_no_method_that_reads_G_is_inherited(self):
        inherited = {m for m in _methods_touching_G(KnowledgeGraph)
                     if m not in SqliteGraph.__dict__ and m not in self.PICKLE_ONLY}
        assert not inherited, f"SqliteGraph would hit `.G` through: {sorted(inherited)}"

    def test_pickle_only_set_is_really_unreachable(self):
        for name in ("_do", "_apply", "__init__"):
            assert name in SqliteGraph.__dict__
        for name in ("save", "_load", "reload_if_changed", "begin_journal", "end_journal",
                     "flush_journal", "maybe_flush"):
            assert name in SqliteGraph.__dict__


class TestBackendSelection:
    def _config(self, **storage):
        path = _store() / "config.json"
        path.write_text(json.dumps({"storage": storage}))

    def test_default_is_networkx(self):
        assert gb.resolve().backend == "networkx"
        assert type(KnowledgeGraph()) is KnowledgeGraph

    def test_config_flag_selects_sqlite(self):
        self._config(graph_backend="sqlite")
        assert gb.resolve() == gb.Resolution("sqlite", "sqlite")
        assert isinstance(KnowledgeGraph(), SqliteGraph)

    def test_env_overrides_config(self, monkeypatch):
        self._config(graph_backend="sqlite")
        monkeypatch.setenv(gb.ENV_VAR, "networkx")
        assert gb.resolve().backend == "networkx"

    def test_encryption_forces_networkx_and_says_why(self, monkeypatch):
        self._config(graph_backend="sqlite")
        monkeypatch.setattr("core.security.get_storage_config", lambda: (True, "p"))
        res = gb.resolve()
        assert (res.backend, res.requested) == ("networkx", "sqlite")
        assert "encrypt" in res.note
        assert type(KnowledgeGraph()) is KnowledgeGraph
        assert not (_store() / "graph" / "graph.sqlite").exists()

    def test_unknown_value_falls_back_with_a_warning(self):
        self._config(graph_backend="postgres")
        with pytest.warns(UserWarning, match="graph_backend"):
            assert gb.resolve().backend == "networkx"

    def test_subclasses_are_never_redirected(self, use):
        use("sqlite")

        class Plain(KnowledgeGraph):
            pass
        assert type(Plain()) is Plain


class TestImporter:
    def _pickle_graph(self, use):
        use("networkx")
        g = KnowledgeGraph()
        build(g)
        g.save()
        return hashlib.sha256((_store() / "graph" / "graph.pkl").read_bytes()).hexdigest()

    def test_first_open_imports_and_leaves_the_pickle_alone(self, use, tmp_path):
        digest = self._pickle_graph(use)
        expected = snapshot(KnowledgeGraph(), str(tmp_path))
        use("sqlite")
        g = KnowledgeGraph()
        got = snapshot(g, str(tmp_path))
        # The import walks edges grouped by source, so a node's *callers* may be listed in a different
        # (but equally arbitrary) order than the order they were first added in; everything else is exact.
        for snap in (got, expected):
            for per in snap["per_node"].values():
                per["pred"] = sorted(per["pred"])
        assert got == expected
        assert g.graph_attr("complete") is True
        info = json.loads(g._one("SELECT value FROM meta WHERE key='import_state'")[0])
        assert (info["nodes"], info["edges"]) == (expected["counts"][0], expected["counts"][1])
        assert hashlib.sha256((_store() / "graph" / "graph.pkl").read_bytes()).hexdigest() == digest

    def test_importing_is_idempotent_and_never_overwrites_newer_rows(self, use):
        self._pickle_graph(use)
        use("sqlite")
        g = KnowledgeGraph()
        g.add_node("fresh", NodeType.CONCEPT)
        g.save()
        g.close()
        again = KnowledgeGraph()
        assert again.node_exists("fresh")
        assert again.node_count() == KnowledgeGraph().node_count()

    def test_a_populated_database_is_not_imported_into(self, use):
        use("sqlite")
        g = KnowledgeGraph()
        g.add_node("only", NodeType.CONCEPT)
        g.save()
        g.close()
        self._pickle_graph(use)             # a pickle appears later (flag flipped back and forth)
        use("sqlite")
        assert KnowledgeGraph().node_ids() == ["only"]

    def test_journal_ops_not_yet_in_the_pickle_are_imported(self, use):
        use("networkx")
        g = KnowledgeGraph()
        g.add_node("saved", NodeType.CONCEPT)
        g.save()
        g.begin_journal()
        g.add_node("journalled", NodeType.CONCEPT)
        g.flush_journal()
        g.end_journal()                      # graph.journal now holds an op the pickle lacks
        use("sqlite")
        assert sorted(KnowledgeGraph().node_ids()) == ["journalled", "saved"]

    def test_a_failed_import_leaves_nothing_and_the_next_open_succeeds(self, use, monkeypatch):
        self._pickle_graph(use)
        use("sqlite")
        calls = {"n": 0}
        real = sg.dumps

        def flaky(attrs):
            calls["n"] += 1
            if calls["n"] == 4:
                raise RuntimeError("disk full")
            return real(attrs)
        monkeypatch.setattr(sg, "dumps", flaky)
        with pytest.raises(RuntimeError, match="disk full"):
            KnowledgeGraph()
        monkeypatch.setattr(sg, "dumps", real)
        g = KnowledgeGraph()
        assert g.node_count() > 4 and g._one("SELECT 1 FROM meta WHERE key='import_state'")

    def test_empty_or_missing_pickle_imports_nothing(self, use):
        use("sqlite")
        g = KnowledgeGraph()
        assert g.node_count() == 0 and g._one("SELECT 1 FROM meta WHERE key='import_state'") is None


class TestSharedDatabase:
    def test_commit_is_visible_to_another_instance_and_reload_says_so(self, use):
        use("sqlite")
        reader, writer = KnowledgeGraph(), KnowledgeGraph()
        assert reader.reload_if_changed() is False
        writer.add_node("n", NodeType.CONCEPT)
        assert reader.node_exists("n") is False          # not committed yet: other processes see the old state
        writer.save()
        assert reader.node_exists("n") is True
        assert reader.reload_if_changed() is True
        assert reader.reload_if_changed() is False

    def test_an_unsaved_transaction_is_committed_when_idle(self, use, monkeypatch):
        monkeypatch.setattr(sg, "IDLE_COMMIT_SECS", 0.15)
        use("sqlite")
        writer, reader = KnowledgeGraph(), KnowledgeGraph()
        writer.add_node("n", NodeType.CONCEPT)
        deadline = time.monotonic() + 5
        while not reader.node_exists("n") and time.monotonic() < deadline:
            time.sleep(0.05)
        assert reader.node_exists("n")

    def test_adjacency_cache_is_refreshed_after_another_writer_commits(self, use, monkeypatch):
        monkeypatch.setattr(sg, "_FRESHNESS_SECS", 0.0)
        use("sqlite")
        a, b = KnowledgeGraph(), KnowledgeGraph()
        a.add_edge("x", "y", EdgeType.CALLS)
        a.save()
        assert b.successors("x") == ["y"]
        a.add_edge("x", "z", EdgeType.CALLS)
        a.save()
        assert b.successors("x") == ["y", "z"]

    def test_corrupt_database_is_quarantined_and_a_fresh_one_started(self, use):
        use("sqlite")
        path = _store() / "graph" / "graph.sqlite"
        path.write_bytes(b"this is not a database" * 100)
        with pytest.warns(UserWarning, match="Quarantined"):
            g = KnowledgeGraph()
        assert g.node_count() == 0
        assert list(path.parent.glob("graph.sqlite.corrupt-*"))

    def test_a_newer_schema_is_refused_not_downgraded(self, use):
        use("sqlite")
        g = KnowledgeGraph()
        g._db().execute("UPDATE meta SET value='99' WHERE key='schema_version'")
        g.close()
        with pytest.raises(RuntimeError, match="newer cognirepo"):
            KnowledgeGraph()


class TestIndexRun:
    def test_second_writer_is_refused_while_a_run_holds_the_lease(self, use):
        use("sqlite")
        first, second = KnowledgeGraph(), KnowledgeGraph()
        first.begin_journal()
        try:
            with pytest.raises(JournalBusy):
                second.begin_journal(wait=0)
        finally:
            first.end_journal()
        second.begin_journal(wait=0)                     # released
        second.end_journal()

    def test_a_killed_run_keeps_its_committed_batches(self, use, tmp_path):
        script = textwrap.dedent("""
            import os
            from data.graph.knowledge_graph import KnowledgeGraph
            g = KnowledgeGraph()
            g.begin_journal(flush_ops=10)
            for i in range(25):
                g.add_node(f"n{i}", "FILE")
            os._exit(9)       # 20 ops committed (two flushes); the last 5 were still in the open transaction
        """)
        env = {**os.environ, gb.ENV_VAR: "sqlite", "PYTHONPATH": str(_REPO)}
        proc = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env, check=False)
        assert proc.returncode == 9
        use("sqlite")
        g = KnowledgeGraph()
        assert g.node_ids() == [f"n{i}" for i in range(20)]
        g.begin_journal(wait=0)                          # the dead run's lease died with it
        g.end_journal()

    def test_flushes_publish_one_change_batch_each(self, use):
        use("sqlite")
        store = str(get_cognirepo_dir())
        g = KnowledgeGraph()
        g.begin_journal(flush_ops=3)
        base = graph_seq.read(store)
        for i in range(7):
            g.add_node(f"n{i}", NodeType.CONCEPT)
        assert graph_seq.read(store) == base + 2         # flushes after ops 3 and 6
        g.end_journal()
        assert graph_seq.read(store) == base + 3         # the remainder
        g.save()
        assert graph_seq.read(store) == base + 3         # nothing new to publish
        assert graph_seq.read_stats(store) == {"nodes": 7, "edges": 0}

    def test_graph_delta_events_describe_the_batch(self, use, monkeypatch):
        from core import events
        monkeypatch.delenv("COGNIREPO_EVENTS", raising=False)
        monkeypatch.delenv("COGNIREPO_EVENTS_METADATA_ONLY", raising=False)
        use("sqlite")
        store = str(get_cognirepo_dir())
        g = KnowledgeGraph()
        g.add_edge("a", "b", EdgeType.CALLS)
        g.set_node_attrs("a", note="x")
        g.remove_node("b")
        g.save()
        batches = [e for e in events.read_since(store, 0, 1000) if e["type"] == "graph.delta"]
        assert [e["graph_seq"] for e in batches] == [1]
        assert [op["op"] for op in batches[0]["ops"]] == ["add_edge", "update_node", "del_node"]
        assert graph_seq.read(store) == 1


class TestBoundedSearches:
    def test_paths_beyond_the_bound_answer_not_connected(self, use, monkeypatch):
        use("sqlite")
        monkeypatch.setattr(sg, "MAX_DEPTH", 3)
        g = KnowledgeGraph()
        for i in range(6):
            g.add_edge(f"n{i}", f"n{i + 1}", EdgeType.CALLS)
        assert g.shortest_path("n0", "n3") == ["n0", "n1", "n2", "n3"]
        assert g.shortest_path("n0", "n5") is None
        assert g.hop_distance("n0", "n5") == sys.maxsize
        assert g.undirected_snapshot().hops("n5", "n3") == 2

    def test_subgraph_skips_hubs_and_reports_truncation(self, use):
        use("sqlite")
        g = KnowledgeGraph()
        for i in range(30):
            g.add_edge("hub", f"leaf{i}", EdgeType.CALLS)
        out = g.subgraph_around("leaf0", radius=2, hub_degree_limit=10)
        assert [n["node_id"] for n in out["nodes"]] == ["leaf0"]
        out = g.subgraph_around("hub", radius=1, max_nodes=5)
        assert out["truncated"] is True and len(out["nodes"]) == 5


class TestWriteLockIsNotHeldForAWholeRun:
    def test_an_index_run_commits_often_enough_for_other_writers(self, use, monkeypatch):
        monkeypatch.setattr(sg, "MAX_FLUSH_SECS", 0.05)
        use("sqlite")
        a, b = KnowledgeGraph(), KnowledgeGraph()
        a.begin_journal(flush_ops=10**6, flush_secs=600)      # configured: flush every 10 minutes
        a.add_node("one", NodeType.CONCEPT)
        assert b.node_exists("one") is False
        time.sleep(0.1)
        a.maybe_flush()                                       # the indexer calls this after every file
        assert b.node_exists("one") is True
        a.end_journal()


class TestRealCliOnSqlite:
    """The actual `index-repo`, in real processes, on the SQLite backend."""

    def _run(self, repo, *args):
        env = {**os.environ, "COGNIREPO_NO_WATCHER": "1", "COGNIREPO_GLOBAL_DIR": str(repo / ".g"),
               "PYTHONPATH": str(_REPO)}
        return subprocess.run([sys.executable, "-m", "interface.cli.main", *args], cwd=repo, env=env,
                              capture_output=True, text=True, timeout=240, check=False)

    def _repo(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / ".cognirepo" / "watchers").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".cognirepo" / "config.json").write_text(json.dumps({"storage": {"graph_backend": "sqlite"}}))
        for i in range(6):
            (tmp_path / f"m{i}.py").write_text(f"def f{i}():\n    return g{i}()\n\ndef g{i}():\n    return {i}\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false",
                        "commit", "-qm", "x"], cwd=tmp_path, check=True)
        return tmp_path

    def test_full_then_incremental_then_two_at_once(self, tmp_path):
        repo = self._repo(tmp_path)
        full = self._run(repo, "index-repo", ".", "--no-embed", "--no-watch")
        assert full.returncode == 0, full.stdout + full.stderr
        store = repo / ".cognirepo" / "graph"
        assert (store / "graph.sqlite").exists() and not (store / "graph.pkl").exists()

        g = KnowledgeGraph()
        assert isinstance(g, SqliteGraph) and g.graph_attr("complete") is True
        callers = [n for n in g.node_ids() if n.endswith("::g3")]
        assert callers and any(g.predecessors(n) for n in callers), "g3 is called by f3"
        g.close()

        (repo / "m0.py").write_text("def f0():\n    return 1\n\ndef brand_new():\n    return 2\n")
        inc = self._run(repo, "index-repo", "--changed-only")
        assert inc.returncode == 0, inc.stdout + inc.stderr
        g = KnowledgeGraph()
        assert any(n.endswith("::brand_new") for n in g.node_ids())
        assert not any(n.endswith("m0.py::g0") for n in g.node_ids()), "removed symbol is gone"
        g.close()

        env = {**os.environ, "COGNIREPO_NO_WATCHER": "1", "COGNIREPO_GLOBAL_DIR": str(repo / ".g"),
               "PYTHONPATH": str(_REPO)}
        argv = [sys.executable, "-m", "interface.cli.main", "index-repo", "--changed-only"]
        procs = [subprocess.Popen(argv, cwd=repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True) for _ in range(2)]
        outs = [(p.communicate(timeout=240)[0], p.returncode) for p in procs]
        assert 0 in [rc for _, rc in outs], outs
        for text, rc in outs:
            assert rc in (0, 75) or "already running" in text, (rc, text)
        g = KnowledgeGraph()
        assert g._one("PRAGMA integrity_check")[0] == "ok"
        assert g.node_count() > 0


class TestReviewFixes:
    def test_only_real_corruption_quarantines(self, use, monkeypatch):
        use("sqlite")
        KnowledgeGraph().save()
        path = _store() / "graph" / "graph.sqlite"
        real = sg.sqlite3.connect

        def unreadable(*a, **k):
            raise sg.sqlite3.OperationalError("unable to open database file")
        monkeypatch.setattr(sg.sqlite3, "connect", unreadable)
        with pytest.raises(sg.sqlite3.OperationalError, match="unable to open"):
            KnowledgeGraph()
        monkeypatch.setattr(sg.sqlite3, "connect", real)
        assert path.exists() and not list(path.parent.glob("graph.sqlite.corrupt-*"))

    def test_a_busy_writer_is_waited_for_not_failed(self, use, monkeypatch):
        import sqlite3
        import threading
        monkeypatch.setattr(sg, "BUSY_TIMEOUT_SECS", 0.05)       # each attempt gives up fast ...
        use("sqlite")
        KnowledgeGraph().save()
        holder = sqlite3.connect(str(_store() / "graph" / "graph.sqlite"), isolation_level=None,
                                 check_same_thread=False)
        holder.execute("BEGIN IMMEDIATE")                         # ... while another process holds the lock
        threading.Timer(0.6, lambda: holder.execute("COMMIT")).start()
        g = KnowledgeGraph()
        g.add_node("n", NodeType.CONCEPT)                         # retried until the lock is free
        g.save()
        assert g.node_exists("n")
        holder.close()

    def test_lock_wait_gives_up_eventually(self, use, monkeypatch):
        import sqlite3
        monkeypatch.setattr(sg, "BUSY_TIMEOUT_SECS", 0.05)
        monkeypatch.setattr(sg, "LOCK_WAIT_SECS", 0.3)
        use("sqlite")
        KnowledgeGraph().save()
        holder = sqlite3.connect(str(_store() / "graph" / "graph.sqlite"), isolation_level=None)
        holder.execute("BEGIN IMMEDIATE")
        g = KnowledgeGraph()
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            g.add_node("n", NodeType.CONCEPT)
        holder.execute("COMMIT")
        holder.close()

    def test_a_write_keeps_the_cached_lists_it_did_not_touch(self, use):
        use("sqlite")
        g = KnowledgeGraph()
        g.add_edge("a", "b", EdgeType.CALLS)
        g.add_edge("x", "y", EdgeType.CALLS)
        assert g.successors("a") == ["b"] and g.successors("x") == ["y"]
        g.add_edge("a", "c", EdgeType.CALLS)
        assert "x" in g._adj[True] and "a" not in g._adj[True]    # only a's list was dropped
        assert g.successors("a") == ["b", "c"]
        g.set_node_attrs("x", note=1)                              # attribute-only ops drop nothing
        assert "x" in g._adj[True]
        g.remove_node("b")                                         # drops b's neighbours' lists too
        assert g.successors("a") == ["c"] and g.predecessors("c") == ["a"]

    def test_empty_pickle_is_recorded_so_it_is_not_reread(self, use, monkeypatch):
        use("networkx")
        KnowledgeGraph().save()                                    # an empty pickle
        use("sqlite")
        g = KnowledgeGraph()
        assert json.loads(g._one("SELECT value FROM meta WHERE key='import_state'")[0])["nodes"] == 0
        g.close()
        import data.graph.sqlite_import as si
        monkeypatch.setattr(si, "_PickleReader", lambda: pytest.fail("re-read the empty pickle"))
        KnowledgeGraph()

    def test_doctor_note_when_the_other_backends_file_is_newer(self, use):
        use("networkx")
        g = KnowledgeGraph()
        g.add_node("n", NodeType.CONCEPT)
        g.save()
        use("sqlite")
        KnowledgeGraph().close()                                   # imports; both files now exist
        assert gb.switch_note() == ""
        pkl = _store() / "graph" / "graph.pkl"
        future = time.time() + 120
        os.utime(pkl, (future, future))                            # the pickle was written after the database
        assert "graph.pkl is newer than graph.sqlite" in gb.switch_note()
        use("networkx")
        assert gb.switch_note() == ""                              # the pickle IS the newest, and in use
        db = _store() / "graph" / "graph.sqlite"
        os.utime(db, (future + 120, future + 120))
        assert "graph.sqlite is newer than graph.pkl" in gb.switch_note()
