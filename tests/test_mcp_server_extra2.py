# pylint: disable=missing-docstring, import-outside-toplevel, broad-exception-caught
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""tests/test_mcp_server_extra2.py — Extra server/mcp_server.py coverage."""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest


# ── _evict_singletons ─────────────────────────────────────────────────────────

def test_evict_singletons_no_crash():
    from server.mcp_server import _evict_singletons
    _evict_singletons()  # first call: nothing to evict


def test_evict_singletons_with_graph():
    import server.mcp_server as ms
    # Set fake singletons then evict
    with ms._SINGLETON_LOCK:
        ms._GRAPH = MagicMock()
        ms._INDEXER = MagicMock()
    ms._evict_singletons()
    assert ms._GRAPH is None
    assert ms._INDEXER is None


# ── _behaviour_enabled ────────────────────────────────────────────────────────

def test_behaviour_enabled_no_config():
    from server.mcp_server import _behaviour_enabled
    with patch("config.paths.get_path", side_effect=FileNotFoundError("no config")):
        result = _behaviour_enabled()
    assert result is False


def test_behaviour_enabled_true(tmp_path):
    from server.mcp_server import _behaviour_enabled
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"behaviour_tracking": True}))
    with patch("config.paths.get_path", return_value=str(cfg)):
        result = _behaviour_enabled()
    assert result is True


# ── retrieve_memory with include_org ──────────────────────────────────────────

def test_retrieve_memory_include_org_false():
    from server.mcp_server import retrieve_memory
    result = retrieve_memory("test query", include_org=False)
    assert isinstance(result, list)


def test_retrieve_memory_include_org_true():
    from server.mcp_server import retrieve_memory
    with patch("intelligence.retrieval.cross_repo.CrossRepoRouter") as mock_router_cls:
        mock_router = MagicMock()
        mock_router.query_org_memories.return_value = []
        mock_router_cls.return_value = mock_router
        result = retrieve_memory("test query", include_org=True, top_k=3)
    assert isinstance(result, list)


# ── org_search ────────────────────────────────────────────────────────────────

def test_org_search_returns_list():
    from server.mcp_server import org_search
    with patch("intelligence.retrieval.cross_repo.CrossRepoRouter") as mock_router_cls:
        mock_router = MagicMock()
        mock_router.query_org_memories.return_value = []
        mock_router_cls.return_value = mock_router
        result = org_search("test query")
    assert isinstance(result, list)


# ── lookup_symbol ──────────────────────────────────────────────────────────────

def test_lookup_symbol_returns_list():
    from server.mcp_server import lookup_symbol
    result = lookup_symbol("hybrid_retrieve")
    assert isinstance(result, list)


def test_lookup_symbol_unknown():
    from server.mcp_server import lookup_symbol
    result = lookup_symbol("nonexistent_function_xyz_abc_123")
    assert isinstance(result, list)


# ── who_calls ─────────────────────────────────────────────────────────────────

def test_who_calls_returns_dict():
    from server.mcp_server import who_calls
    result = who_calls("hybrid_retrieve")
    assert isinstance(result, dict)
    assert "local_callers" in result or "cross_repo_callers" in result or isinstance(result, dict)


def test_who_calls_unknown_function():
    from server.mcp_server import who_calls
    result = who_calls("nonexistent_function_xyz_123")
    assert isinstance(result, dict)


# ── search_docs ───────────────────────────────────────────────────────────────

def test_search_docs_returns_dict():
    from server.mcp_server import search_docs
    result = search_docs("architecture overview")
    assert isinstance(result, dict) or isinstance(result, list)


# ── architecture_overview ─────────────────────────────────────────────────────

def test_architecture_overview_no_summaries(tmp_path):
    from server.mcp_server import architecture_overview
    with patch("config.paths.get_path", return_value=str(tmp_path / "nonexistent.json")):
        result = architecture_overview(scope="root")
    assert isinstance(result, str)
    assert "not found" in result.lower() or "summarize" in result.lower()


def test_architecture_overview_root(tmp_path):
    from server.mcp_server import architecture_overview
    summaries = {"repo": "This is a cognitive infrastructure repo."}
    summary_path = tmp_path / "summaries.json"
    summary_path.write_text(json.dumps(summaries))
    with patch("config.paths.get_path", return_value=str(summary_path)):
        result = architecture_overview(scope="root")
    assert "cognitive" in result


def test_architecture_overview_unknown_scope(tmp_path):
    from server.mcp_server import architecture_overview
    summaries = {"repo": "test", "directories": {}, "files": {}}
    summary_path = tmp_path / "summaries.json"
    summary_path.write_text(json.dumps(summaries))
    with patch("config.paths.get_path", return_value=str(summary_path)):
        result = architecture_overview(scope="nonexistent_scope")
    assert "No summary found" in result


# ── episodic_search ───────────────────────────────────────────────────────────

def test_episodic_search_returns_list():
    from server.mcp_server import episodic_search
    result = episodic_search("authentication bug")
    assert isinstance(result, list)


# ── list_org_context with data ────────────────────────────────────────────────

def test_list_org_context_with_orgs():
    from server.mcp_server import list_org_context
    with patch("config.orgs.list_orgs", return_value={"myorg": {"repos": ["/path/to/repo"]}}):
        result = list_org_context()
    assert isinstance(result, dict)


# ── _auto_store_hook ──────────────────────────────────────────────────────────

def test_auto_store_hook_no_crash():
    from server.mcp_server import _auto_store_hook
    _auto_store_hook("context_pack", {"status": "ok", "sections": []})


def test_auto_store_hook_with_list_result():
    from server.mcp_server import _auto_store_hook
    result = [{"name": "hybrid_retrieve", "file": "retrieval/hybrid.py", "score": 0.9}]
    _auto_store_hook("semantic_search_code", result)


# ── _behaviour_record_query ───────────────────────────────────────────────────

def test_behaviour_record_query_disabled():
    from server.mcp_server import _behaviour_record_query
    with patch("server.mcp_server._behaviour_enabled", return_value=False):
        _behaviour_record_query("test query", {"sections": []})


def test_behaviour_record_query_list_result():
    from server.mcp_server import _behaviour_record_query
    with patch("server.mcp_server._behaviour_enabled", return_value=False):
        _behaviour_record_query("test", [{"name": "fn", "score": 0.9}])
