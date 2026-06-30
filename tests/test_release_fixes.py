# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Regression tests for the v1.1.0 release-readiness fixes.

Covers: atomic AST index writes + corruption self-heal, skip-dir config,
bounded subgraph expansion, learning-store dedup, dependency_graph module
resolution, and service port detection.
"""
import json
import os

import pytest


# ── atomic save + corruption self-heal (indexer/ast_indexer.py) ───────────────

class TestAtomicIndexPersistence:
    def test_atomic_json_dump_replaces_file(self, tmp_path):
        from intelligence.indexer.ast_indexer import ASTIndexer
        target = str(tmp_path / "out.json")
        ASTIndexer._atomic_json_dump({"a": 1}, target)
        with open(target, encoding="utf-8") as f:
            assert json.load(f) == {"a": 1}
        assert not os.path.exists(target + ".tmp")

    def test_load_json_self_heal_returns_default_on_corruption(self, tmp_path):
        from intelligence.indexer.ast_indexer import ASTIndexer
        target = str(tmp_path / "ast_index.json")
        # Simulate the truncated-mid-write corruption observed on kubernetes
        with open(target, "w", encoding="utf-8") as f:
            f.write('{"files": {"a.py": {"symbols": [')
        result = ASTIndexer._load_json_self_heal(target, {"files": {}})
        assert result == {"files": {}}
        # Corrupt file renamed aside, not left in place
        assert not os.path.exists(target)
        assert os.path.exists(target + ".corrupt")

    def test_load_json_self_heal_reads_valid_file(self, tmp_path):
        from intelligence.indexer.ast_indexer import ASTIndexer
        target = str(tmp_path / "ok.json")
        with open(target, "w", encoding="utf-8") as f:
            json.dump([1, 2, 3], f)
        assert ASTIndexer._load_json_self_heal(target, []) == [1, 2, 3]


# ── skip dirs (indexer/ast_indexer.py) ────────────────────────────────────────

class TestSkipDirs:
    def test_staging_not_skipped_by_default(self):
        from intelligence.indexer.ast_indexer import _SKIP_DIRS
        # staging/ holds real source in Kubernetes-style repos
        assert "staging" not in _SKIP_DIRS
        assert "vendor" in _SKIP_DIRS
        assert "third_party" in _SKIP_DIRS

    def test_go_type_spec_indexed_as_class(self):
        from intelligence.indexer.ast_indexer import _TS_CLASS_TYPES
        assert "type_spec" in _TS_CLASS_TYPES


# ── bounded subgraph (graph/knowledge_graph.py) ───────────────────────────────

class TestBoundedSubgraph:
    def _build_graph(self, fan_out: int):
        from data.graph.knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph.__new__(KnowledgeGraph)  # skip disk load
        import networkx as nx
        kg.G = nx.DiGraph()
        kg.G.add_node("center", type="FUNCTION")
        for i in range(fan_out):
            kg.G.add_node(f"n{i}", type="FUNCTION")
            kg.G.add_edge("center", f"n{i}", rel="CALLS")
        return kg

    def test_node_cap_enforced_during_expansion(self):
        kg = self._build_graph(fan_out=500)
        result = kg.subgraph_around("center", radius=2, max_nodes=50)
        assert len(result["nodes"]) <= 50
        assert result["truncated"] is True

    def test_hub_nodes_skipped(self):
        from data.graph.knowledge_graph import KnowledgeGraph
        import networkx as nx
        kg = KnowledgeGraph.__new__(KnowledgeGraph)
        kg.G = nx.DiGraph()
        kg.G.add_node("center", type="FUNCTION")
        kg.G.add_node("hub", type="FUNCTION")
        kg.G.add_edge("center", "hub", rel="CALLS")
        # hub has 600 other connections — above the limit, must not expand
        for i in range(600):
            kg.G.add_edge("hub", f"h{i}", rel="CALLS")
        result = kg.subgraph_around("center", radius=3, hub_degree_limit=500)
        node_ids = {n["node_id"] for n in result["nodes"]}
        assert "center" in node_ids
        assert "hub" not in node_ids  # skipped as hub
        assert not any(n.startswith("h") and n != "hub" for n in node_ids)

    def test_small_graph_unaffected(self):
        kg = self._build_graph(fan_out=5)
        result = kg.subgraph_around("center", radius=2)
        assert len(result["nodes"]) == 6
        assert result["truncated"] is False


# ── learning store dedup (memory/learning_store.py) ───────────────────────────

class TestLearningStoreDedup:
    def test_identical_text_not_duplicated(self, tmp_path, monkeypatch):
        import data.memory.learning_store as ls_mod
        backend = ls_mod._LearningBackend.__new__(ls_mod._LearningBackend)
        index_file = tmp_path / "learnings.json"
        monkeypatch.setattr(backend, "_index_path", lambda: index_file, raising=False)
        index_file.write_text("[]", encoding="utf-8")

        id1 = backend.store("decision", "Redis cache TTL is 30 minutes", {}, "repo")
        id2 = backend.store("decision", "Redis  cache TTL is 30 minutes ", {}, "repo")
        assert id1 == id2
        records = json.loads(index_file.read_text(encoding="utf-8"))
        assert len(records) == 1

    def test_different_text_stored_separately(self, tmp_path, monkeypatch):
        import data.memory.learning_store as ls_mod
        backend = ls_mod._LearningBackend.__new__(ls_mod._LearningBackend)
        index_file = tmp_path / "learnings.json"
        monkeypatch.setattr(backend, "_index_path", lambda: index_file, raising=False)
        index_file.write_text("[]", encoding="utf-8")

        id1 = backend.store("decision", "Redis cache TTL is 30 minutes", {}, "repo")
        id2 = backend.store("decision", "Redis cache TTL is 1 hour", {}, "repo")
        assert id1 != id2


# ── service port detection (cli/init_project.py) ──────────────────────────────

class TestPortDetection:
    def test_spring_application_properties(self, tmp_path):
        from interface.cli.init_project import _detect_service_port
        res_dir = tmp_path / "src" / "main" / "resources"
        res_dir.mkdir(parents=True)
        (res_dir / "application.properties").write_text(
            "spring.application.name=npci\nserver.port=8082\n", encoding="utf-8"
        )
        assert _detect_service_port(str(tmp_path)) == 8082

    def test_env_port(self, tmp_path):
        from interface.cli.init_project import _detect_service_port
        (tmp_path / ".env").write_text("PORT=3000\nDEBUG=1\n", encoding="utf-8")
        assert _detect_service_port(str(tmp_path)) == 3000

    def test_no_config_returns_none(self, tmp_path):
        from interface.cli.init_project import _detect_service_port
        assert _detect_service_port(str(tmp_path)) is None


# ── .env.example packaging (pyproject + cli/init_project.py) ─────────────────

class TestEnvTemplatePackaging:
    REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_package_copy_exists_and_in_sync_with_root(self):
        # The wheel can only ship files INSIDE a package dir, so the template
        # lives at cognirepo/.env.example; the root copy is for dev installs.
        root = os.path.join(self.REPO_ROOT, ".env.example")
        packaged = os.path.join(self.REPO_ROOT, "cognirepo", ".env.example")
        assert os.path.isfile(packaged), "cognirepo/.env.example missing — wheel won't ship the template"
        with open(root, encoding="utf-8") as f1, open(packaged, encoding="utf-8") as f2:
            assert f1.read() == f2.read(), (
                ".env.example copies out of sync — edit the root file and re-copy "
                "to cognirepo/.env.example"
            )

    def test_template_ships_no_active_breaker_limit(self):
        # An ACTIVE RSS limit in the template capped every initialized project
        # at 2 GB and tripped the circuit breaker constantly. Values must be
        # commented so the 80%-of-RAM default applies.
        with open(os.path.join(self.REPO_ROOT, ".env.example"), encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                assert not stripped.startswith("COGNIREPO_CB_RSS_LIMIT_MB="), (
                    ".env.example must not ship an ACTIVE RSS limit"
                )

    def test_importlib_resources_resolves_template(self):
        import importlib.resources as ir
        assert ir.files("cognirepo").joinpath(".env.example").is_file()


# ── stale-index helpers (server/mcp_server.py) ────────────────────────────────

class TestStaleReindexHelpers:
    def test_watcher_alive_false_without_pidfile(self, tmp_path, monkeypatch):
        import interface.server.mcp_server as srv
        monkeypatch.setattr(
            "config.paths.get_path", lambda rel: str(tmp_path / rel), raising=False
        )
        assert srv._watcher_alive() is False

    def test_spawn_background_reindex_respects_existing_lock(self, tmp_path):
        import interface.server.mcp_server as srv
        lock = tmp_path / "index" / "reindex.lock"
        lock.parent.mkdir(parents=True)
        lock.write_text("", encoding="utf-8")
        # Fresh lock → another reindex in flight → must not spawn
        assert srv._spawn_background_reindex(str(lock)) is False
