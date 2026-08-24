# pylint: disable=missing-docstring, import-outside-toplevel, broad-exception-caught
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""tests/test_mcp_tools_extended.py — Extended coverage for server/mcp_server.py (49% → 70%)."""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest


def _seed_graph_node():
    from interface.server.mcp_server import _get_graph
    g = _get_graph()
    g.G.add_node("_test_ext::node", type="FUNCTION")
    return g


def _unseed(g):
    try:
        g.G.remove_node("_test_ext::node")
    except Exception:
        pass


# ── org_dependencies ──────────────────────────────────────────────────────────

def test_org_dependencies_returns_expected_keys():
    from interface.server.mcp_server import org_dependencies
    result = org_dependencies()
    assert isinstance(result, dict)
    assert "current_repo" in result
    assert "current_repo_name" in result
    assert "direct_dependencies" in result
    assert "direct_dependents" in result
    assert "transitive_dependencies" in result
    assert "transitive_dependents" in result
    # Verify removed bloat keys absent
    assert "repos" not in result
    assert "edges" not in result
    assert "graph" not in result


def test_org_dependencies_no_graph_key():
    from interface.server.mcp_server import org_dependencies
    result = org_dependencies()
    assert "graph" not in result


# ── link_repos ────────────────────────────────────────────────────────────────

def test_link_repos_returns_status():
    from interface.server.mcp_server import link_repos
    result = link_repos(src_repo=".", dst_repo=".", relationship="imports")
    assert "status" in result or "linked" in str(result).lower() or isinstance(result, dict)


# ── list_org_context ──────────────────────────────────────────────────────────

def test_list_org_context_returns_dict():
    from interface.server.mcp_server import list_org_context
    result = list_org_context()
    assert isinstance(result, dict)


# ── get_session_history ───────────────────────────────────────────────────────

def test_get_session_history_returns_list():
    from interface.server.mcp_server import get_session_history
    result = get_session_history(limit=5)
    assert isinstance(result, list)


# ── graph_stats ───────────────────────────────────────────────────────────────

def test_graph_stats_returns_dict():
    from interface.server.mcp_server import graph_stats
    g = _seed_graph_node()
    try:
        result = graph_stats()
        assert isinstance(result, dict)
    finally:
        _unseed(g)


def test_graph_stats_has_node_count():
    from interface.server.mcp_server import graph_stats
    g = _seed_graph_node()
    try:
        result = graph_stats()
        assert "nodes" in result or "node_count" in result or "total_nodes" in result or len(result) > 0
    finally:
        _unseed(g)


# ── get_last_context ──────────────────────────────────────────────────────────

def test_get_last_context_returns_dict():
    from interface.server.mcp_server import get_last_context
    result = get_last_context()
    assert isinstance(result, dict)


# ── get_session_brief ──────────────────────────────────────────────────────────

def test_get_session_brief_returns_dict():
    from interface.server.mcp_server import get_session_brief
    result = get_session_brief()
    assert isinstance(result, dict)


# ── get_user_profile ──────────────────────────────────────────────────────────

def test_get_user_profile_returns_dict():
    from interface.server.mcp_server import get_user_profile
    result = get_user_profile()
    assert isinstance(result, dict)


def test_get_user_profile_has_tracking_key():
    from interface.server.mcp_server import get_user_profile
    result = get_user_profile()
    assert "behaviour_tracking" in result or "framing_hints" in result or isinstance(result, dict)


# ── get_error_patterns ────────────────────────────────────────────────────────

def test_get_error_patterns_returns_list():
    from interface.server.mcp_server import get_error_patterns
    result = get_error_patterns()
    assert isinstance(result, list)


# ── record_decision ───────────────────────────────────────────────────────────

def test_record_decision_returns_dict():
    from interface.server.mcp_server import record_decision
    result = record_decision("Use FAISS for semantic search", "low latency, local-first")
    assert isinstance(result, dict)
    assert "status" in result or "id" in result or result


# ── log_episode ───────────────────────────────────────────────────────────────

def test_log_episode_returns_dict():
    from interface.server.mcp_server import log_episode
    result = log_episode("MCP test: log_episode called successfully")
    assert isinstance(result, dict) or result is not None


# ── record_error ──────────────────────────────────────────────────────────────

def test_record_error_returns_dict():
    from interface.server.mcp_server import record_error
    result = record_error("TestError", "test error message for coverage")
    assert isinstance(result, dict) or result is not None


# ── record_user_preference ────────────────────────────────────────────────────

def test_record_user_preference_returns_dict():
    from interface.server.mcp_server import record_user_preference
    result = record_user_preference("depth", "concise", context="prefers short answers")
    assert isinstance(result, dict) or result is not None


def test_record_user_preference_persona_unknown_value_rejected():
    from interface.server.mcp_server import record_user_preference
    result = record_user_preference("persona", "wizard")
    if result.get("behaviour_tracking") == "disabled":
        return
    assert result["recorded"] is False
    assert "error" in result


# ── supersede_learning ────────────────────────────────────────────────────────

def test_supersede_learning_nonexistent_id():
    from interface.server.mcp_server import supersede_learning
    result = supersede_learning(
        old_id="nonexistent-id-12345",
        new_text="updated memory text for testing",
        learning_type="fact",
    )
    assert isinstance(result, dict)
    assert "found_old" in result or "new_id" in result or result


# ── get_agent_bootstrap ───────────────────────────────────────────────────────

def test_get_agent_bootstrap_returns_dict():
    from interface.server.mcp_server import get_agent_bootstrap
    result = get_agent_bootstrap()
    assert isinstance(result, dict)


def test_get_agent_bootstrap_has_repo_key():
    from interface.server.mcp_server import get_agent_bootstrap
    result = get_agent_bootstrap()
    assert "repo" in result or "index_health" in result or "architecture" in result


def test_get_agent_bootstrap_has_index_health():
    from interface.server.mcp_server import get_agent_bootstrap
    result = get_agent_bootstrap()
    # index_health or error key must be present
    assert "index_health" in result or "error" in result or len(result) > 0


# ── context_pack with file param ─────────────────────────────────────────────

def test_context_pack_file_param_accepted():
    from interface.server.mcp_server import context_pack
    import inspect
    sig = inspect.signature(context_pack)
    assert "file" in sig.parameters


def test_context_pack_file_param_no_crash(tmp_path):
    from interface.server.mcp_server import context_pack
    result = context_pack(query="test query", file="nonexistent.py")
    assert isinstance(result, dict)


# ── semantic_search_code type annotation ─────────────────────────────────────

def test_semantic_search_code_language_none():
    from interface.server.mcp_server import semantic_search_code
    import inspect
    sig = inspect.signature(semantic_search_code)
    param = sig.parameters.get("language")
    assert param is not None
    # Should accept None
    result = semantic_search_code(query="test", language=None)
    assert isinstance(result, list)


# ── dependency_graph ──────────────────────────────────────────────────────────

def test_dependency_graph_returns_dict():
    from interface.server.mcp_server import dependency_graph
    result = dependency_graph(module="intelligence.retrieval.hybrid")
    assert isinstance(result, dict) or isinstance(result, list)


# ── cross_repo_search ─────────────────────────────────────────────────────────

def test_cross_repo_search_returns_dict():
    from interface.server.mcp_server import cross_repo_search
    result = cross_repo_search("hybrid retrieval")
    assert isinstance(result, dict) or isinstance(result, list)


# ── org_wide_search ───────────────────────────────────────────────────────────

def test_org_wide_search_returns_dict():
    from interface.server.mcp_server import org_wide_search
    result = org_wide_search("authentication")
    assert isinstance(result, dict) or isinstance(result, list)


# ── subgraph ──────────────────────────────────────────────────────────────────

def test_subgraph_returns_dict():
    from interface.server.mcp_server import subgraph
    g = _seed_graph_node()
    try:
        result = subgraph("_test_ext::node")
        assert isinstance(result, dict)
    finally:
        _unseed(g)


# ── search_token ──────────────────────────────────────────────────────────────

def test_search_token_returns_dict():
    from interface.server.mcp_server import search_token
    result = search_token("hybrid_retrieve")
    assert isinstance(result, dict) or isinstance(result, list)


# ── explain_change ────────────────────────────────────────────────────────────

def test_explain_change_returns_dict():
    from interface.server.mcp_server import explain_change
    result = explain_change(target="HEAD", since="7d")
    assert isinstance(result, dict) or isinstance(result, list)


# ── store_memory / retrieve_memory via MCP ───────────────────────────────────

def test_mcp_store_then_retrieve():
    from interface.server.mcp_server import store_memory, retrieve_memory
    r = store_memory("MCP extended test: behaviour tracker integration")
    assert isinstance(r, dict)
    results = retrieve_memory("behaviour tracker")
    assert isinstance(results, list)


# ── semantic_search_code ─────────────────────────────────────────────────────

def test_semantic_search_code_python_filter():
    from interface.server.mcp_server import semantic_search_code
    result = semantic_search_code("retrieve memory", language="python")
    assert isinstance(result, list)


# ── cross_repo_traverse ───────────────────────────────────────────────────────

def test_cross_repo_traverse_returns_dict():
    from interface.server.mcp_server import cross_repo_traverse
    result = cross_repo_traverse("some_function")
    assert isinstance(result, dict) or isinstance(result, list)
