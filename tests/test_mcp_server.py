# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

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
        from memory.episodic_memory import log_event, get_history
        log_event("mcp tool called: store_memory", {"source": "mcp"})
        history = get_history(1)
        assert len(history) >= 1
        assert "store_memory" in history[0]["event"]

    def test_manifest_written(self):
        import importlib.util
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

    def test_who_calls_returns_list(self):
        from server.mcp_server import who_calls
        g = _seed_graph_node()
        try:
            result = who_calls("nonexistent_fn_xyz")
            assert isinstance(result, list)
            assert result == []
        finally:
            _unseed_graph_node(g)

    def test_who_calls_entries_have_required_fields(self):
        from server.mcp_server import who_calls
        g = _seed_graph_node()
        try:
            result = who_calls("log_event")
            for entry in result:
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
        from memory.episodic_memory import log_event
        from server.mcp_server import episodic_search
        log_event("error occurred during test run", {"source": "test"})
        result = episodic_search("error", limit=5)
        assert isinstance(result, list)

    def test_episodic_search_matches_keyword(self):
        from memory.episodic_memory import log_event
        from server.mcp_server import episodic_search
        log_event("unique_keyword_abc123 event logged")
        result = episodic_search("unique_keyword_abc123", limit=10)
        assert len(result) >= 1
        assert any("unique_keyword_abc123" in json.dumps(e) for e in result)

    def test_episodic_search_limit_respected(self):
        from memory.episodic_memory import log_event
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
    """A2.3 — MCP tools return a structured warning when the graph is empty."""

    def test_lookup_symbol_warns_when_graph_empty(self):
        from server.mcp_server import lookup_symbol, _get_graph
        # conftest isolates to tmp_path → graph is always empty
        graph = _get_graph()
        assert graph.G.number_of_nodes() == 0, "graph should be empty in test"
        result = lookup_symbol("anything")
        assert isinstance(result, dict)
        assert "warning" in result
        assert "results" in result
        assert result["results"] == []

    def test_who_calls_warns_when_graph_empty(self):
        from server.mcp_server import who_calls
        result = who_calls("anything")
        assert isinstance(result, dict)
        assert "warning" in result

    def test_subgraph_warns_when_graph_empty(self):
        from server.mcp_server import subgraph
        result = subgraph("jwt_auth", depth=2)
        assert isinstance(result, dict)
        assert "warning" in result

    def test_warning_message_contains_index_repo_hint(self):
        from server.mcp_server import lookup_symbol
        result = lookup_symbol("anything")
        assert "index-repo" in result["warning"]

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
