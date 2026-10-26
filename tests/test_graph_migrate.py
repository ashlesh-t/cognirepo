# Copyright (c) 2026 Ashlesh T. — AGPL-3.0 (see LICENSE)
"""Graph backend migration (both directions), verification, rollback, and the backend recommendation."""
from __future__ import annotations

import json
import os
import pathlib

import pytest

from core.config.paths import get_cognirepo_dir
from core.config.store_settings import SettingsError, set_value
from data.graph import backend as gb
from data.graph import migrate as mg
from data.graph.journal import WriterLease
from data.graph.knowledge_graph import EdgeType, KnowledgeGraph, NodeType
from tests.test_graph_backends import build, snapshot


def _store() -> pathlib.Path:
    return pathlib.Path(get_cognirepo_dir())


@pytest.fixture
def repo(isolated_cognirepo):
    (_store() / "config.json").write_text("{}")
    return _store()


def _cfg(repo) -> dict:
    return json.loads((repo / "config.json").read_text())


def _networkx_graph(repo):
    os.environ.pop(gb.ENV_VAR, None)
    g = KnowledgeGraph()
    build(g)
    g.save()


def _canon(snap):
    for per in snap["per_node"].values():
        per["pred"] = sorted(per["pred"])
    return snap


class TestRoundTrip:
    def test_networkx_to_sqlite_and_back_is_lossless(self, repo, tmp_path):
        _networkx_graph(repo)
        before = _canon(snapshot(KnowledgeGraph(), str(tmp_path)))

        out = mg.migrate("sqlite")
        assert (out["from"], out["to"], out["changed_setting"]) == ("networkx", "sqlite", True)
        assert _cfg(repo)["storage"]["graph_backend"] == "sqlite" and out["verified"] > 0
        assert type(KnowledgeGraph()).__name__ == "SqliteGraph"
        assert _canon(snapshot(KnowledgeGraph(), str(tmp_path))) == before
        assert (repo / "graph" / "graph.pkl").exists(), "the source is never touched"

        back = mg.migrate("networkx", replace=True)
        assert _cfg(repo)["storage"]["graph_backend"] == "networkx"
        assert back["kept"] and all(os.path.exists(k) for k in back["kept"])
        assert type(KnowledgeGraph()).__name__ == "KnowledgeGraph"
        assert _canon(snapshot(KnowledgeGraph(), str(tmp_path))) == before

    def test_progress_phases_are_reported_in_order(self, repo):
        _networkx_graph(repo)
        seen = []
        mg.migrate("sqlite", progress=lambda e: seen.append(e["phase"]))
        assert seen[0] == "prepare" and seen[-1] == "done"
        assert seen.index("verify") < seen.index("switch") < seen.index("done")

    def test_sqlite_only_repo_migrates_to_networkx(self, repo, monkeypatch):
        monkeypatch.setenv(gb.ENV_VAR, "sqlite")
        g = KnowledgeGraph()
        build(g)
        g.save()
        g.close()
        monkeypatch.delenv(gb.ENV_VAR)
        assert not (repo / "graph" / "graph.pkl").exists()
        out = mg.migrate("networkx")
        assert out["nodes"] == KnowledgeGraph().node_count() > 0
        assert KnowledgeGraph().graph_attr("complete") is True or KnowledgeGraph().G.graph.get("complete")


class TestSafety:
    def test_a_failed_verification_undoes_everything_and_keeps_the_setting(self, repo, monkeypatch):
        _networkx_graph(repo)
        mg.migrate("sqlite")
        good_db = (repo / "graph" / "graph.sqlite").read_bytes()
        set_value(str(repo), "storage", "graph_backend", "networkx")

        def boom(*_a, **_k):
            raise mg.MigrationError("verify_failed", "forced")
        monkeypatch.setattr(mg, "_verify", boom)
        with pytest.raises(mg.MigrationError) as exc:
            mg.migrate("sqlite", replace=True)
        assert exc.value.code == "verify_failed"
        assert _cfg(repo)["storage"]["graph_backend"] == "networkx"
        assert (repo / "graph" / "graph.sqlite").read_bytes() == good_db, "the set-aside database came back"
        assert not list((repo / "graph").glob("*.replaced-*"))

    def test_refuses_to_overwrite_without_replace(self, repo):
        _networkx_graph(repo)
        mg.migrate("sqlite")
        with pytest.raises(mg.MigrationError) as exc:
            mg.migrate("sqlite")
        assert exc.value.code == "target_exists"
        assert (repo / "graph" / "graph.sqlite").exists()

    def test_replace_sets_the_old_pickle_and_its_journal_aside(self, repo):
        _networkx_graph(repo)
        mg.migrate("sqlite")
        (repo / "graph" / "graph.journal").write_bytes(b"leftover")
        out = mg.migrate("networkx", replace=True)
        kept = sorted(os.path.basename(k) for k in out["kept"])
        assert any(k.startswith("graph.pkl.replaced-") for k in kept)
        assert any(k.startswith("graph.journal.replaced-") for k in kept)
        assert not (repo / "graph" / "graph.journal").exists(), "a leftover journal would replay over the export"

    def test_busy_when_an_index_run_holds_the_lease(self, repo):
        _networkx_graph(repo)
        lease = WriterLease(str(repo / "graph" / "graph.journal"))
        lease.acquire(0)
        try:
            with pytest.raises(mg.MigrationError) as exc:
                mg.migrate("sqlite")
            assert exc.value.code == "busy"
        finally:
            lease.release()
        assert not (repo / "graph" / "graph.sqlite").exists()
        assert "graph_backend" not in _cfg(repo).get("storage", {})

    def test_encryption_blocks_sqlite(self, repo):
        _networkx_graph(repo)
        (repo / "config.json").write_text(json.dumps({"storage": {"encrypt": True}}))
        with pytest.raises(mg.MigrationError) as exc:
            mg.migrate("sqlite")
        assert exc.value.code == "encryption_on"

    def test_nothing_to_migrate_from(self, repo):
        with pytest.raises(mg.MigrationError) as exc:
            mg.migrate("sqlite")
        assert exc.value.code == "no_source"

    def test_an_empty_database_shell_is_replaced_without_asking(self, repo, monkeypatch):
        monkeypatch.setenv(gb.ENV_VAR, "sqlite")
        KnowledgeGraph().close()                       # creates an empty graph.sqlite
        monkeypatch.delenv(gb.ENV_VAR)
        _networkx_graph(repo)
        assert mg.migrate("sqlite")["nodes"] > 0

    def test_bad_target(self, repo):
        with pytest.raises(mg.MigrationError) as exc:
            mg.plan("postgres")
        assert exc.value.code == "bad_target"


class TestPlan:
    def test_plan_changes_nothing(self, repo):
        _networkx_graph(repo)
        before = sorted(p.name for p in (repo / "graph").iterdir())
        cfg = (repo / "config.json").read_text()
        info = mg.plan("sqlite")
        assert info["from"] == "networkx" and info["nodes"] and info["edges"] and info["blockers"] == []
        assert info["needs_replace"] is False and info["ram_mb"] is not None
        assert sorted(p.name for p in (repo / "graph").iterdir()) == before
        assert (repo / "config.json").read_text() == cfg

    def test_plan_reports_what_would_be_set_aside_and_blockers(self, repo):
        _networkx_graph(repo)
        mg.migrate("sqlite")
        info = mg.plan("sqlite")
        assert info["needs_replace"] is True and info["moves_aside"] == ["graph.sqlite"]
        back = mg.plan("networkx")                      # right after the copy both files hold the same graph
        assert back["up_to_date"] is True and back["needs_replace"] is True
        os.utime(_store() / "graph" / "graph.sqlite", (4_000_000_000, 4_000_000_000))
        assert mg.plan("networkx")["up_to_date"] is False        # the database has moved on since
        assert mg.plan("sqlite")["up_to_date"] is True
        assert mg.plan("sqlite", count=False)["nodes"] is None


class TestBackendHelpers:
    def test_set_value_keeps_the_rest_and_reports_change(self, repo):
        (repo / "config.json").write_text(json.dumps({"a": 1, "storage": {"encrypt": False}}))
        assert set_value(str(repo), "storage", "graph_backend", "sqlite") is True
        assert set_value(str(repo), "storage", "graph_backend", "sqlite") is False
        assert _cfg(repo) == {"a": 1, "storage": {"encrypt": False, "graph_backend": "sqlite"}}

    def test_set_value_refuses_a_missing_config(self, repo):
        (repo / "config.json").unlink()
        with pytest.raises(SettingsError) as exc:
            set_value(str(repo), "storage", "graph_backend", "sqlite")
        assert exc.value.code == "not_initialised"

    @pytest.mark.parametrize("nodes,sessions,encrypted,use,conf", [
        (500, 1, False, "networkx", "clear"),
        (30_000, 1, False, "networkx", "either"),
        (30_000, 4, False, "sqlite", "leaning"),
        (150_000, 1, False, "sqlite", "clear"),
        (150_000, 1, True, "networkx", "clear"),
        (None, 1, False, "networkx", "either"),
    ])
    def test_recommendation(self, nodes, sessions, encrypted, use, conf):
        rec = gb.recommend(nodes, sessions, encrypted)
        assert (rec.use, rec.confidence) == (use, conf) and rec.reasons

    def test_is_current_follows_the_setting(self, repo, monkeypatch):
        monkeypatch.delenv(gb.ENV_VAR, raising=False)
        old = KnowledgeGraph()
        assert gb.is_current(old)
        set_value(str(repo), "storage", "graph_backend", "sqlite")
        assert not gb.is_current(old)
        new = KnowledgeGraph()
        assert gb.is_current(new) and not gb.is_current(old)

    def test_needs_migration_tracks_the_other_files_age(self, repo):
        _networkx_graph(repo)
        store = str(repo)
        assert gb.needs_migration(store, "sqlite") is True       # nothing there yet
        assert gb.needs_migration(store, "networkx") is False    # nothing to carry over
        mg.migrate("sqlite")
        assert gb.needs_migration(store, "sqlite") is False
        os.utime(repo / "graph" / "graph.pkl", (4_000_000_000, 4_000_000_000))
        assert gb.needs_migration(store, "sqlite") is True       # the pickle moved on


class TestRunningProcessesFollowTheSwitch:
    """Agents, the watcher and cached retrievers must move to the new backend, not keep writing to the old one."""

    @pytest.fixture(autouse=True)
    def _current_sqlite_module(self):
        # Other tests reload data.graph.knowledge_graph, leaving an older SqliteGraph subclassing an older class;
        # re-import it so the dispatch sees a subclass of the KnowledgeGraph these tests construct.
        import sys
        sys.modules.pop("data.graph.sqlite_graph", None)
        yield

    def test_the_mcp_server_singleton_is_rebuilt_on_its_next_call(self, repo, monkeypatch):
        import interface.server.mcp_server as ms
        monkeypatch.delenv(gb.ENV_VAR, raising=False)
        monkeypatch.setattr(ms, "_GRAPH", None)
        monkeypatch.setattr(ms, "_INDEXER", None)
        first = ms._get_graph()
        assert type(first).__name__ == "KnowledgeGraph" and ms._get_graph() is first
        set_value(str(repo), "storage", "graph_backend", "sqlite")
        second = ms._get_graph()
        assert type(second).__name__ == "SqliteGraph" and ms._get_graph() is second

    def test_the_watcher_swaps_graph_indexer_and_behaviour_together(self, repo, monkeypatch):
        from types import SimpleNamespace
        from intelligence.indexer.file_watcher import RepoFileHandler
        monkeypatch.delenv(gb.ENV_VAR, raising=False)
        old = KnowledgeGraph()
        fake = SimpleNamespace(graph=old, indexer=SimpleNamespace(graph=old), behaviour=SimpleNamespace(graph=old))
        RepoFileHandler._follow_backend(fake)
        assert fake.graph is old, "nothing changed, nothing swapped"
        set_value(str(repo), "storage", "graph_backend", "sqlite")
        RepoFileHandler._follow_backend(fake)
        assert type(fake.graph).__name__ == "SqliteGraph"
        assert fake.indexer.graph is fake.graph and fake.behaviour.graph is fake.graph

    def test_the_shared_retriever_is_dropped_when_its_graph_is_stale(self, repo, monkeypatch):
        from types import SimpleNamespace
        import intelligence.orchestrator.context_builder as cb
        monkeypatch.delenv(gb.ENV_VAR, raising=False)
        built = []
        monkeypatch.setattr(cb, "HybridRetriever", lambda: built.append(1) or SimpleNamespace(graph=KnowledgeGraph()))
        monkeypatch.setattr(cb, "_SHARED_RETRIEVER", None)
        first = cb._get_retriever()
        assert cb._get_retriever() is first and len(built) == 1
        set_value(str(repo), "storage", "graph_backend", "sqlite")
        assert cb._get_retriever() is not first and len(built) == 2


class TestCli:
    def test_backend_json_matches_the_files(self, repo, capsys):
        from interface.cli.main import _cmd_graph_backend
        _networkx_graph(repo)
        assert _cmd_graph_backend(as_json=True) == 0
        st = json.loads(capsys.readouterr().out)
        assert st["active"] == "networkx" and st["files"]["networkx"]["exists"] and st["switch_to"] == "sqlite"

    def test_migrate_dry_run_json(self, repo, capsys):
        from interface.cli.main import _cmd_graph_migrate
        _networkx_graph(repo)
        assert _cmd_graph_migrate("sqlite", dry_run=True, as_json=True) == 0
        plan = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert plan["result"] == "plan" and plan["to"] == "sqlite" and not (repo / "graph" / "graph.sqlite").exists()

    def test_a_running_watcher_is_refused_unless_it_may_be_stopped_and_is_restarted_after(self, repo, capsys, monkeypatch):
        import interface.cli.main as cli
        from interface.cli import daemon as cd
        _networkx_graph(repo)
        rec = {"pid": 99999999, "kind": "standalone", "path": str(repo)}
        monkeypatch.setattr(cd, "is_watcher_running_for_path", lambda _p: rec)
        assert cli._cmd_graph_migrate("sqlite", as_json=True) == 2
        assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["code"] == "watcher_running"
        assert not (repo / "graph" / "graph.sqlite").exists()

        monkeypatch.setattr(cd, "stop_watcher_and_wait", lambda _p: "failed")
        assert cli._cmd_graph_migrate("sqlite", stop_watcher=True, as_json=True) == 1
        assert not (repo / "graph" / "graph.sqlite").exists(), "a watcher that will not stop means nothing is changed"
        capsys.readouterr()

        restarted = []
        monkeypatch.setattr(cd, "stop_watcher_and_wait", lambda _p: "stopped")
        monkeypatch.setattr(cli, "_restart_watcher", lambda root, was: restarted.append(was))
        assert cli._cmd_graph_migrate("sqlite", stop_watcher=True, as_json=True) == 0
        assert restarted == [rec] and (repo / "graph" / "graph.sqlite").exists()

    def test_an_embedded_watcher_is_left_alone(self, repo, monkeypatch):
        import interface.cli.main as cli
        from interface.cli import daemon as cd
        _networkx_graph(repo)
        monkeypatch.setattr(cd, "is_watcher_running_for_path", lambda _p: {"pid": 5, "kind": "embedded"})
        monkeypatch.setattr(cd, "stop_watcher_and_wait", lambda _p: pytest.fail("must not signal an agent's server"))
        assert cli._cmd_graph_migrate("sqlite", as_json=True) == 0

    def test_exit_codes_for_refusals(self, repo, capsys, monkeypatch):
        import interface.cli.main as cli
        from interface.cli import daemon as cd
        monkeypatch.setattr(cd, "is_watcher_running_for_path", lambda _p: None)
        assert cli._cmd_graph_migrate("sqlite", as_json=True) == 2           # nothing to migrate from
        assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["code"] == "no_source"
        _networkx_graph(repo)
        lease = WriterLease(str(repo / "graph" / "graph.journal"))
        lease.acquire(0)
        try:
            assert cli._cmd_graph_migrate("sqlite", as_json=True) == 75      # an index run owns the graph
        finally:
            lease.release()
