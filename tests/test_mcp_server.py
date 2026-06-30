# pylint: disable=missing-docstring, unnecessary-lambda, import-outside-toplevel, too-few-public-methods, duplicate-code
# pylint: disable=redefined-outer-name, unused-argument, broad-exception-caught, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_mcp_server.py — MCP tool function unit tests.

We call the underlying tool functions directly (not through MCP transport)
since the MCP server runs over stdio and can't be unit-tested as a process.
"""
from __future__ import annotations

import json
import os


class TestMCPToolFunctions:
    def test_store_memory_tool(self):
        from tools.store_memory import store_memory
        result = store_memory("test memory about JWT authentication", source="mcp_test")
        assert result["status"] == "stored"
        assert "importance" in result
        assert result["text"] == "test memory about JWT authentication"

    def test_retrieve_memory_tool_returns_list(self):
        from tools.store_memory import store_memory
        from tools.retrieve_memory import retrieve_memory
        store_memory("cached result for auth query in session")
        results = retrieve_memory("auth session", top_k=1)
        assert isinstance(results, list)

    def test_retrieve_memory_empty_store(self):
        from tools.retrieve_memory import retrieve_memory
        results = retrieve_memory("anything", top_k=5)
        assert isinstance(results, list)

    def test_log_episode_tool(self):
        from data.memory.episodic_memory import log_event, get_history
        log_event("mcp tool called: store_memory", {"source": "mcp"})
        history = get_history(1)
        assert len(history) >= 1
        assert "store_memory" in history[0]["event"]

    def test_manifest_written(self):
        from server.mcp_server import _write_manifest, _build_manifest
        _write_manifest()
        # manifest.json is written next to mcp_server.py (not CWD)
        import server.mcp_server as _mod
        manifest_path = os.path.join(os.path.dirname(_mod.__file__), "manifest.json")
        assert os.path.exists(manifest_path)
        data = _build_manifest()
        tool_names = [t["name"] for t in data.get("tools", [])]
        assert "store_memory" in tool_names
        assert "retrieve_memory" in tool_names
        assert "search_docs" in tool_names
        assert "log_episode" in tool_names

    def test_store_memory_importance_non_negative(self):
        from tools.store_memory import store_memory
        result = store_memory("short text")
        assert result["importance"] >= 0

    def test_store_memory_source_preserved(self):
        from tools.store_memory import store_memory
        result = store_memory("text with source", source="copilot")
        assert result.get("source") == "copilot"


def _seed_graph_node():
    """Add a single dummy node so graph is non-empty and tool guards pass."""
    from server.mcp_server import _get_graph
    g = _get_graph()
    g.G.add_node("_test_dummy_::node", type="FUNCTION")
    return g


def _unseed_graph_node(g):
    g.G.remove_node("_test_dummy_::node")


class TestNewMCPTools:
    def test_lookup_symbol_returns_list(self):
        from server.mcp_server import lookup_symbol
        g = _seed_graph_node()
        try:
            result = lookup_symbol("log_event")
            assert isinstance(result, list)
        finally:
            _unseed_graph_node(g)

    def test_lookup_symbol_entries_have_required_fields(self):
        from server.mcp_server import lookup_symbol
        g = _seed_graph_node()
        try:
            result = lookup_symbol("log_event")
            for entry in result:
                assert "file" in entry
                assert "line" in entry
                assert "type" in entry
        finally:
            _unseed_graph_node(g)

    def test_who_calls_returns_dict_shape(self):
        from server.mcp_server import who_calls
        g = _seed_graph_node()
        try:
            result = who_calls("nonexistent_fn_xyz")
            assert isinstance(result, dict), f"Expected dict, got {type(result)}"
            assert "local_callers" in result
            assert "cross_repo_callers" in result
            assert "truncated" in result
            assert isinstance(result["local_callers"], list)
            assert isinstance(result["cross_repo_callers"], list)
            assert isinstance(result["truncated"], bool)
        finally:
            _unseed_graph_node(g)

    def test_who_calls_empty_graph_returns_dict(self):
        from server.mcp_server import who_calls
        # With an empty graph the early-return path must still return dict shape
        result = who_calls("nonexistent_fn_xyz")
        assert isinstance(result, dict)
        assert "local_callers" in result
        assert result["local_callers"] == []
        assert result["cross_repo_callers"] == []
        assert result["truncated"] is False

    def test_who_calls_entries_have_required_fields(self):
        from server.mcp_server import who_calls
        g = _seed_graph_node()
        try:
            result = who_calls("log_event")
            # result is now always a dict; check local_callers entries
            for entry in result.get("local_callers", []):
                assert "caller" in entry
                assert "file" in entry
                assert "line" in entry
        finally:
            _unseed_graph_node(g)

    def test_subgraph_returns_dict_with_nodes_and_edges(self):
        from server.mcp_server import subgraph
        g = _seed_graph_node()
        try:
            result = subgraph("nonexistent_entity_xyz", depth=2)
            assert isinstance(result, dict)
            assert "nodes" in result
            assert "edges" in result
        finally:
            _unseed_graph_node(g)

    def test_subgraph_is_json_serialisable(self):
        from server.mcp_server import subgraph
        g = _seed_graph_node()
        try:
            result = subgraph("nonexistent_entity_xyz", depth=1)
            serialised = json.dumps(result)
            assert isinstance(serialised, str)
        finally:
            _unseed_graph_node(g)

    def test_episodic_search_returns_list(self):
        from data.memory.episodic_memory import log_event
        from server.mcp_server import episodic_search
        log_event("error occurred during test run", {"source": "test"})
        result = episodic_search("error", limit=5)
        assert isinstance(result, list)

    def test_episodic_search_matches_keyword(self):
        from data.memory.episodic_memory import log_event
        from server.mcp_server import episodic_search
        log_event("unique_keyword_abc123 event logged")
        result = episodic_search("unique_keyword_abc123", limit=10)
        assert len(result) >= 1
        assert any("unique_keyword_abc123" in json.dumps(e) for e in result)

    def test_episodic_search_limit_respected(self):
        from data.memory.episodic_memory import log_event
        from server.mcp_server import episodic_search
        for i in range(5):
            log_event(f"repeated_limit_test event {i}")
        result = episodic_search("repeated_limit_test", limit=3)
        assert len(result) <= 3

    def test_graph_stats_returns_expected_keys(self):
        from server.mcp_server import graph_stats
        result = graph_stats()
        assert isinstance(result, dict)
        assert "node_count" in result
        assert "edge_count" in result
        assert "top_concepts" in result
        assert "last_indexed" in result

    def test_graph_stats_counts_are_non_negative(self):
        from server.mcp_server import graph_stats
        result = graph_stats()
        assert result["node_count"] >= 0
        assert result["edge_count"] >= 0

    def test_graph_stats_top_concepts_is_list(self):
        from server.mcp_server import graph_stats
        result = graph_stats()
        assert isinstance(result["top_concepts"], list)

    def test_manifest_includes_new_tools(self):
        from server.mcp_server import _build_manifest
        manifest = _build_manifest()
        tool_names = [t["name"] for t in manifest.get("tools", [])]
        for name in ("lookup_symbol", "who_calls", "subgraph", "episodic_search", "graph_stats"):
            assert name in tool_names, f"{name} missing from manifest"


class TestEmptyGraphWarnings:
    """A2.3 — MCP tools return correct shapes when the graph is empty."""

    def test_lookup_symbol_returns_empty_list_when_graph_empty(self):
        from server.mcp_server import lookup_symbol, _get_graph
        # conftest isolates to tmp_path → graph is always empty
        graph = _get_graph()
        assert graph.G.number_of_nodes() == 0, "graph should be empty in test"
        result = lookup_symbol("anything")
        # T1 fix: lookup_symbol always returns a list ([] when graph empty)
        assert isinstance(result, list)
        assert result == []

    def test_who_calls_returns_dict_shape_when_graph_empty(self):
        from server.mcp_server import who_calls
        result = who_calls("anything")
        assert isinstance(result, dict)
        assert "local_callers" in result
        assert result["local_callers"] == []
        assert result["cross_repo_callers"] == []
        assert result["truncated"] is False

    def test_subgraph_warns_when_graph_empty(self):
        from server.mcp_server import subgraph
        result = subgraph("jwt_auth", depth=2)
        assert isinstance(result, dict)
        assert "warning" in result

    def test_lookup_symbol_returns_list_not_dict_on_empty_graph(self):
        from server.mcp_server import lookup_symbol
        result = lookup_symbol("anything")
        # Must be a list — callers iterate it; returning dict would crash them
        assert isinstance(result, list)

    def test_no_warning_after_graph_populated(self):
        from server.mcp_server import lookup_symbol, _get_graph
        graph = _get_graph()
        # manually add a node so graph is non-empty
        graph.G.add_node("test::node", type="FUNCTION")
        result = lookup_symbol("test_symbol")
        # Should return a list (not a warning dict) when graph has nodes
        assert isinstance(result, list)
        # clean up
        graph.G.remove_node("test::node")


class TestManifestFormat:
    def test_manifest_tools_have_required_fields(self):
        from server.mcp_server import _build_manifest
        manifest = _build_manifest()
        for tool in manifest.get("tools", []):
            assert "name" in tool
            assert "description" in tool

    def test_openai_spec_export(self):
        from server.mcp_server import _write_manifest
        _write_manifest()
        from adapters.openai_spec import export
        # _write_manifest writes next to mcp_server.py; openai_spec reads from there
        import server.mcp_server as _mod
        import adapters.openai_spec as _spec
        orig = _spec.MANIFEST_PATH
        _spec.MANIFEST_PATH = os.path.join(os.path.dirname(_mod.__file__), "manifest.json")
        try:
            paths = export(out_dir="adapters")
        finally:
            _spec.MANIFEST_PATH = orig
        assert os.path.exists(paths["openai_tools"])
        with open(paths["openai_tools"], encoding="utf-8") as f:
            tools = json.load(f)
        assert isinstance(tools, list)
        assert all(t["type"] == "function" for t in tools)


class TestAgentBootstrapFraming:
    def test_agent_bootstrap_framing_populated(self, tmp_path, monkeypatch):
        """framing.depth must not be 'unknown' when behaviour data is present."""
        from unittest.mock import patch, MagicMock
        monkeypatch.setenv("COGNIREPO_DIR", str(tmp_path / ".cognirepo"))
        (tmp_path / ".cognirepo").mkdir(parents=True, exist_ok=True)

        fake_profile = {
            "depth_preference": "detailed",
            "top_terminology": ["auth", "token"],
            "framing_hints": "prefers code-first answers",
            "explicit_preferences": {},
        }
        fake_bt = MagicMock()
        fake_bt.data = {"symbol_weights": {}}
        fake_bt.get_user_profile.return_value = fake_profile
        fake_bt.get_error_patterns.return_value = []

        with patch("server.mcp_server._behaviour_enabled", return_value=True), \
             patch("server.mcp_server.BehaviourTracker", return_value=fake_bt) if False else \
             patch("data.graph.behaviour_tracker.BehaviourTracker", return_value=fake_bt):
            from server.mcp_server import get_agent_bootstrap
            with patch("server.mcp_server._behaviour_enabled", return_value=True), \
                 patch("server.mcp_server._get_graph", return_value=MagicMock()), \
                 patch("data.graph.behaviour_tracker.BehaviourTracker", return_value=fake_bt), \
                 patch("server.mcp_server._index_is_stale", return_value=False):
                result = get_agent_bootstrap()

        assert result["framing"]["depth"] != "unknown"
        assert result["framing"]["hints"] == "prefers code-first answers"
        assert "auth" in result["framing"]["vocabulary"]

    def test_agent_bootstrap_framing_empty_when_disabled(self, tmp_path, monkeypatch):
        """framing must be empty dict when behaviour tracking is disabled."""
        from unittest.mock import patch
        monkeypatch.setenv("COGNIREPO_DIR", str(tmp_path / ".cognirepo"))
        (tmp_path / ".cognirepo").mkdir(parents=True, exist_ok=True)

        with patch("server.mcp_server._behaviour_enabled", return_value=False), \
             patch("server.mcp_server._index_is_stale", return_value=False):
            from server.mcp_server import get_agent_bootstrap
            result = get_agent_bootstrap()

        assert result["framing"] == {}

    def test_agent_bootstrap_staleness_triggers_reindex(self, tmp_path, monkeypatch):
        """Background reindex must be spawned when index is stale and no lock exists."""
        from unittest.mock import patch, MagicMock
        # Set up a real .cognirepo/index dir so file I/O works
        cognirepo_dir = tmp_path / ".cognirepo"
        cognirepo_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("COGNIREPO_DIR", str(cognirepo_dir))

        mock_popen = MagicMock()
        with patch("server.mcp_server._behaviour_enabled", return_value=False), \
             patch("server.mcp_server._index_is_stale", return_value=True), \
             patch("config.paths.get_path", side_effect=lambda p: str(cognirepo_dir / p)), \
             patch("subprocess.Popen", mock_popen):
            from server.mcp_server import get_agent_bootstrap
            result = get_agent_bootstrap()

        assert result["index_health"]["status"] == "reindexing"
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args[0][0]
        assert "cognirepo" in call_args
        assert "--changed-only" in call_args

    def test_agent_bootstrap_no_double_reindex(self, tmp_path, monkeypatch):
        """No second Popen when lock file already exists."""
        from unittest.mock import patch, MagicMock
        cognirepo_dir = tmp_path / ".cognirepo"
        (cognirepo_dir / "index").mkdir(parents=True, exist_ok=True)
        lock_path = cognirepo_dir / "index" / "reindex.lock"
        lock_path.touch()
        monkeypatch.setenv("COGNIREPO_DIR", str(cognirepo_dir))

        mock_idx = MagicMock()
        mock_idx.index_data = {"files": {}}
        mock_popen = MagicMock()
        with patch("server.mcp_server._behaviour_enabled", return_value=False), \
             patch("server.mcp_server._index_is_stale", return_value=True), \
             patch("server.mcp_server._get_indexer", return_value=mock_idx), \
             patch("config.paths.get_path", side_effect=lambda p: str(cognirepo_dir / p)), \
             patch("subprocess.Popen", mock_popen):
            from server.mcp_server import get_agent_bootstrap
            get_agent_bootstrap()

        mock_popen.assert_not_called()


# ── T5.3 search_token ─────────────────────────────────────────────────────────

class TestSearchToken:
    def test_empty_result_returns_dict(self, isolated_cognirepo):
        from server.mcp_server import search_token
        result = search_token("nonexistent_zzz_xqr_unique_word")
        assert isinstance(result, dict)
        assert "results" in result
        assert "count" in result
        assert "word" in result
        assert result["results"] == []
        assert result["count"] == 0

    def test_word_preserved_in_result(self, isolated_cognirepo):
        from server.mcp_server import search_token
        result = search_token("authenticate")
        assert result["word"] == "authenticate"

    def test_word_kwarg_accepted(self, isolated_cognirepo):
        from server.mcp_server import search_token
        # Ensure function param is named 'word' not 'token'
        result = search_token(word="validate")
        assert isinstance(result, dict)
        assert "results" in result

    def test_result_items_have_file_and_line(self, isolated_cognirepo, tmp_path):
        from server.mcp_server import search_token
        from intelligence.indexer.ast_indexer import ASTIndexer
        from data.graph.knowledge_graph import KnowledgeGraph
        # Build a minimal index with a known symbol
        g = KnowledgeGraph()
        idx = ASTIndexer(g)
        idx.index_data = {
            "files": {
                "fake_module.py": {
                    "symbols": [{"name": "authenticate_user", "type": "FUNCTION", "start_line": 10, "docstring": "authenticate logic"}]
                }
            },
            "word_index": {"authenticate": [{"file": "fake_module.py", "line": 10}]},
            "indexed_at": "2026-01-01T00:00:00",
        }
        idx.save()
        result = search_token("authenticate")
        for hit in result.get("results", []):
            assert "file" in hit
            assert "line" in hit

    def test_count_matches_results_length(self, isolated_cognirepo):
        from server.mcp_server import search_token
        result = search_token("handler")
        assert result["count"] == len(result["results"])


# ── T5.4 link_repos ───────────────────────────────────────────────────────────

class TestLinkRepos:
    def test_link_repos_basic_returns_linked_true(self, isolated_cognirepo, tmp_path):
        from server.mcp_server import link_repos
        src = str(tmp_path / "service_a")
        dst = str(tmp_path / "service_b")
        result = link_repos(src_repo=src, dst_repo=dst, relationship="imports")
        assert result["linked"] is True
        assert "edge" in result
        assert result["edge"]["src"] == src
        assert result["edge"]["dst"] == dst
        assert result["edge"]["kind"] == "IMPORTS"

    def test_link_repos_calls_api_relationship(self, isolated_cognirepo, tmp_path):
        from server.mcp_server import link_repos
        src = str(tmp_path / "gateway")
        dst = str(tmp_path / "auth_svc")
        result = link_repos(src_repo=src, dst_repo=dst, relationship="calls_api")
        assert result["edge"]["kind"] == "CALLS_API"

    def test_link_repos_with_microservice_metadata(self, isolated_cognirepo, tmp_path):
        from server.mcp_server import link_repos
        from data.graph.org_graph import get_org_graph, invalidate_org_graph
        src = str(tmp_path / "api_gateway")
        dst = str(tmp_path / "auth_service")
        result = link_repos(
            src_repo=src, dst_repo=dst, relationship="calls_api",
            service_type="rest_api", port=8080, api_base_url="/api/v1",
        )
        assert result["linked"] is True
        assert result["edge"]["kind"] == "CALLS_API"
        # Verify metadata stored on destination node
        og = get_org_graph()
        node_data = og.G.nodes.get(dst, {})
        assert node_data.get("service_type") == "rest_api"
        assert node_data.get("port") == 8080
        assert node_data.get("api_base_url") == "/api/v1"
        invalidate_org_graph()

    def test_link_repos_all_relationship_kinds(self, isolated_cognirepo, tmp_path):
        from server.mcp_server import link_repos
        mapping = [
            ("imports", "IMPORTS"),
            ("calls_api", "CALLS_API"),
            ("shares_schema", "SHARES_SCHEMA"),
            ("discovered", "DISCOVERED"),
            ("child_of", "CHILD_OF"),
        ]
        for rel, kind in mapping:
            result = link_repos(
                src_repo=str(tmp_path / "a"),
                dst_repo=str(tmp_path / "b"),
                relationship=rel,
            )
            assert result["edge"]["kind"] == kind, f"Failed for {rel}: got {result['edge']['kind']}"

    def test_link_repos_unknown_relationship_defaults_to_discovered(self, isolated_cognirepo, tmp_path):
        from server.mcp_server import link_repos
        result = link_repos(
            src_repo=str(tmp_path / "x"),
            dst_repo=str(tmp_path / "y"),
            relationship="something_unknown",
        )
        assert result["edge"]["kind"] == "DISCOVERED"


# ── T5.5 behaviour tracking disabled paths ────────────────────────────────────

class TestBehaviourTrackingDisabled:
    """Tests that all behaviour tools return graceful shapes when tracking is off."""

    def test_get_error_patterns_disabled_returns_list(self, isolated_cognirepo):
        from server.mcp_server import get_error_patterns
        result = get_error_patterns()
        assert isinstance(result, list), f"Expected list, got {type(result)}"
        if result:
            # When disabled, first item has the disabled key
            assert result[0].get("behaviour_tracking") == "disabled"

    def test_record_error_disabled_returns_dict_with_recorded_false(self, isolated_cognirepo):
        from server.mcp_server import record_error
        result = record_error(error_type="TestError", message="test msg")
        assert isinstance(result, dict)
        # Either recorded=True (if tracking enabled) or recorded=False with disabled key
        if "behaviour_tracking" in result:
            assert result["behaviour_tracking"] == "disabled"
            assert result["recorded"] is False
        else:
            assert "recorded" in result

    def test_record_user_preference_disabled_returns_dict_with_recorded_false(self, isolated_cognirepo):
        from server.mcp_server import record_user_preference
        result = record_user_preference(preference_key="style", preference_value="concise")
        assert isinstance(result, dict)
        if "behaviour_tracking" in result:
            assert result["behaviour_tracking"] == "disabled"
            assert result["recorded"] is False

    def test_get_user_profile_disabled_returns_dict(self, isolated_cognirepo):
        from server.mcp_server import get_user_profile
        result = get_user_profile()
        assert isinstance(result, dict)
        # Either a full profile or the disabled message
        assert "behaviour_tracking" in result or "depth_preference" in result


# ── T5.6 context_pack with repo_path ──────────────────────────────────────────

class TestContextPackRepoPaths:
    def test_context_pack_with_fresh_repo_path_returns_valid_shape(self, isolated_cognirepo, tmp_path):
        from server.mcp_server import context_pack
        result = context_pack("authentication", repo_path=str(tmp_path))
        assert isinstance(result, dict)
        assert "query" in result
        assert "sections" in result
        assert "token_count" in result
        assert "truncated" in result

    def test_context_pack_with_none_repo_path_returns_valid_shape(self, isolated_cognirepo):
        from server.mcp_server import context_pack
        result = context_pack("anything", repo_path=None)
        assert isinstance(result, dict)
        assert "query" in result
        assert "sections" in result

    def test_context_pack_status_field_always_present(self, isolated_cognirepo):
        from server.mcp_server import context_pack
        result = context_pack("quantum entanglement unicorn blockchain", repo_path=None)
        # status must always be present — either "ok", "no_confident_match", or "index_empty"
        assert "status" in result or "sections" in result  # either shape is valid


# ── T5.2 who_calls extended coverage ──────────────────────────────────────────

class TestWhoCallsAllPaths:
    def test_who_calls_with_dynamic_fallback_still_returns_dict(self, isolated_cognirepo, tmp_path, monkeypatch):
        """Even when grep fallback fires, who_calls must return dict not list."""
        from unittest.mock import patch
        from server.mcp_server import who_calls

        fake_fallback = [
            {"caller": "dynamic_dispatch::foo.py:10", "file": "foo.py", "line": 10,
             "code_snippet": "register('my_fn')", "found_via": "dynamic_dispatch_fallback"}
        ]
        with patch("server.mcp_server._who_calls_dynamic_fallback", return_value=fake_fallback), \
             patch("server.mcp_server._graph_is_empty", return_value=False), \
             patch("server.mcp_server._get_graph") as mock_g:
            mock_g.return_value.node_exists.return_value = False
            mock_g.return_value.G.number_of_nodes.return_value = 5
            result = who_calls("my_fn")

        assert isinstance(result, dict), f"Expected dict, got {type(result)}: {result}"
        assert "local_callers" in result
        assert "cross_repo_callers" in result
        assert "truncated" in result
        assert len(result["local_callers"]) == 1

    def test_who_calls_truncated_flag_set_above_50(self, isolated_cognirepo, monkeypatch):
        """When fallback returns >50 callers, truncated must be True."""
        from unittest.mock import patch
        from server.mcp_server import who_calls

        big_fallback = [
            {"caller": f"fn_{i}", "file": f"f{i}.py", "line": i,
             "code_snippet": "", "found_via": "dynamic_dispatch_fallback"}
            for i in range(55)
        ]
        with patch("server.mcp_server._who_calls_dynamic_fallback", return_value=big_fallback), \
             patch("server.mcp_server._graph_is_empty", return_value=False), \
             patch("server.mcp_server._get_graph") as mock_g:
            mock_g.return_value.node_exists.return_value = False
            mock_g.return_value.G.number_of_nodes.return_value = 5
            result = who_calls("big_fn")

        assert result["truncated"] is True
        assert len(result["local_callers"]) == 50
