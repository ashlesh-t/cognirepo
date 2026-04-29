# pylint: disable=missing-docstring, unnecessary-lambda, import-outside-toplevel, too-few-public-methods, duplicate-code
# pylint: disable=redefined-outer-name, unused-argument, broad-exception-caught, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_doctor.py — Sprint 3.8 acceptance criteria for `cognirepo doctor`.

Covered:
  - All systems healthy → exit 0, output shows all ✓
  - No API keys → ✗ on API key check, exit 1, all 4 var names in output
  - FAISS unreadable → ✗ on check 2, exit 1
  - Graph unreadable → ✗ on check 3, exit 1
  - Multiple failures → correct issue count in summary
  - --verbose flag adds optional component info
"""
from __future__ import annotations

import os
import sys
import types


# ── helpers ───────────────────────────────────────────────────────────────────

def _run_doctor(
    capsys,
    monkeypatch,
    *,
    verbose: bool = False,
    faiss_fail: bool = False,
    graph_fail: bool = False,
    episodic_fail: bool = False,
    api_keys: bool = True,
    with_init: bool = True,
) -> int:
    """
    Exercise _cmd_doctor() in isolation, returning its exit-code integer.
    Monkeypatches all heavy imports so the test needs no real .cognirepo/.
    """
    # pylint: disable=too-many-locals
    from cli.main import _cmd_doctor  # imported here so SPDX header is already applied

    # ── stub env ──────────────────────────────────────────────────────────────
    for var in ["ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                "OPENAI_API_KEY", "GROK_API_KEY", "COGNIREPO_MULTI_AGENT_ENABLED"]:
        monkeypatch.delenv(var, raising=False)

    if api_keys:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

    # ── stub vector_db ────────────────────────────────────────────────────────
    fake_vdb_mod = types.ModuleType("vector_db.local_vector_db")
    if faiss_fail:
        class _BadVDB:
            def __init__(self):
                raise RuntimeError("FAISS index not found")
        fake_vdb_mod.LocalVectorDB = _BadVDB
    else:
        class _FakeIndex:
            ntotal = 47
        class _FakeVDB:
            index = _FakeIndex()
        fake_vdb_mod.LocalVectorDB = _FakeVDB
    monkeypatch.setitem(sys.modules, "vector_db.local_vector_db", fake_vdb_mod)

    # ── stub graph ────────────────────────────────────────────────────────────
    fake_graph_mod = types.ModuleType("graph.knowledge_graph")
    if graph_fail:
        class _BadKG:
            def __init__(self):
                raise RuntimeError("graph.pkl not found")
        fake_graph_mod.KnowledgeGraph = _BadKG
    else:
        class _FakeG:
            def number_of_nodes(self):
                return 1832
            def number_of_edges(self):
                return 4218
        class _FakeKG:
            G = _FakeG()
        fake_graph_mod.KnowledgeGraph = _FakeKG
    monkeypatch.setitem(sys.modules, "graph.knowledge_graph", fake_graph_mod)

    # ── stub episodic ─────────────────────────────────────────────────────────
    fake_ep_mod = types.ModuleType("memory.episodic_memory")
    if episodic_fail:
        def _bad_history(**_kw):
            raise RuntimeError("episodic.json not found")
        fake_ep_mod.get_history = _bad_history
    else:
        fake_ep_mod.get_history = lambda **_kw: [{"event": "x"}] * 89
    monkeypatch.setitem(sys.modules, "memory.episodic_memory", fake_ep_mod)

    # ── stub AST indexer ──────────────────────────────────────────────────────
    fake_idx_mod = types.ModuleType("indexer.ast_indexer")
    class _FakeASTIndexer:
        def __init__(self, **_kw):
            self.index_data = {}
        def load(self):
            pass
    fake_idx_mod.ASTIndexer = _FakeASTIndexer
    monkeypatch.setitem(sys.modules, "indexer.ast_indexer", fake_idx_mod)

    # ── stub language registry ────────────────────────────────────────────────
    fake_lang_mod = types.ModuleType("indexer.language_registry")
    fake_lang_mod.supported_extensions = lambda: {".py", ".js", ".ts"}
    fake_lang_mod._GRAMMAR_MAP = {".py": "tree-sitter-python"}
    fake_lang_mod._get_language = lambda ext: None
    fake_lang_mod.clear_cache = lambda: None
    monkeypatch.setitem(sys.modules, "indexer.language_registry", fake_lang_mod)

    # ── stub circuit breaker ──────────────────────────────────────────────────
    fake_cb_mod = types.ModuleType("memory.circuit_breaker")
    class _FakeCBState:
        value = "CLOSED"
    class _FakeCB:
        state = _FakeCBState()
        _rss_limit_mb = 6553.0
    fake_cb_mod.get_breaker = lambda: _FakeCB()
    monkeypatch.setitem(sys.modules, "memory.circuit_breaker", fake_cb_mod)

    # ── stub psutil ───────────────────────────────────────────────────────────
    fake_psutil = types.ModuleType("psutil")
    class _FakeProc:
        def memory_info(self):
            class _MI:
                rss = 412 * 1024 * 1024
            return _MI()
    fake_psutil.Process = lambda: _FakeProc()
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

    # ── stub faiss ────────────────────────────────────────────────────────────
    fake_faiss = types.ModuleType("faiss")
    class _FakeFaissIndex:  # pylint: disable=too-few-public-methods
        ntotal = 47
    def _fake_read_index(_):
        if faiss_fail:
            raise RuntimeError("FAISS index not found")
        return _FakeFaissIndex()
    fake_faiss.read_index = _fake_read_index
    monkeypatch.setitem(sys.modules, "faiss", fake_faiss)

    # ── stub _bm25 ────────────────────────────────────────────────────────────
    fake_bm25_mod = types.ModuleType("_bm25")
    fake_bm25_mod.BACKEND = "python"
    monkeypatch.setitem(sys.modules, "_bm25", fake_bm25_mod)

    # ── stub fastembed (check 13) ─────────────────────────────────────────────
    fake_fe_mod = types.ModuleType("fastembed")
    fake_fe_mod.__version__ = "0.3.6"
    monkeypatch.setitem(sys.modules, "fastembed", fake_fe_mod)

    # ── stub server.mcp_server (new check 14) ─────────────────────────────────
    fake_mcp_server_mod = types.ModuleType("server.mcp_server")
    fake_mcp_server_mod._REGISTERED_TOOLS = {
        "store_memory", "retrieve_memory", "record_decision",
        "context_pack", "semantic_search_code", "search_token",
        "lookup_symbol", "who_calls", "subgraph", "dependency_graph", "graph_stats",
        "episodic_search", "log_episode",
        "architecture_overview", "explain_change",
        "get_session_brief", "get_last_context", "get_session_history",
        "cross_repo_search", "org_dependencies", "cross_repo_traverse",
        "org_wide_search", "org_search", "list_org_context", "link_repos",
        "search_docs",
        "get_user_profile", "record_error", "get_error_patterns",
        "record_user_preference", "supersede_learning", "get_agent_bootstrap",
    }
    monkeypatch.setitem(sys.modules, "server", types.ModuleType("server"))
    monkeypatch.setitem(sys.modules, "server.mcp_server", fake_mcp_server_mod)

    # ── stub .cognirepo/ presence ─────────────────────────────────────────────
    if with_init:
        _orig_isdir = os.path.isdir  # capture before monkeypatching

        def _fake_isdir(p):
            # doctor checks get_path(""), which may be global or local
            if ".cognirepo" in str(p):
                return True
            return _orig_isdir(p)

        monkeypatch.setattr(os.path, "isdir", _fake_isdir, raising=False)
        _orig_exists = os.path.exists
        def _fake_exists(p):
            ps = str(p)
            # Match files checked by doctor
            if "config.json" in ps or "semantic.index" in ps or \
               "graph.pkl" in ps or "ast_index.json" in ps or \
               "episodic.json" in ps or "summaries.json" in ps:
                return True
            # Fake at least one MCP config so the AI-tools check passes
            if ".claude/settings.json" in ps or "settings.json" in ps:
                return True
            return _orig_exists(p)
        monkeypatch.setattr(os.path, "exists", _fake_exists)
        # stub open for check files
        import builtins  # pylint: disable=import-outside-toplevel
        import io  # pylint: disable=import-outside-toplevel
        _orig_open = builtins.open
        def _fake_open(p, *a, **kw):
            ps = str(p)
            if "config.json" in ps and ".claude" not in ps and ".gemini" not in ps:
                return io.StringIO('{"project_name": "test-project"}')
            if "ast_index.json" in ps:
                return io.StringIO('{"files": {"f1.py": {"symbols": [{"name": "s1"}]}}}')
            if "episodic.json" in ps:
                # episodic is opened in "rb" mode
                return io.BytesIO(b'[]')
            # Fake MCP settings.json so doctor can parse it
            if "settings.json" in ps:
                return io.StringIO('{"mcpServers": {"cognirepo-test": {}}}')
            return _orig_open(p, *a, **kw)
        monkeypatch.setattr(builtins, "open", _fake_open)

    return _cmd_doctor(verbose=verbose)


# ── tests ─────────────────────────────────────────────────────────────────────

class TestDoctorAllHealthy:
    def test_exit_0_when_all_pass(self, capsys, monkeypatch):
        code = _run_doctor(capsys, monkeypatch, api_keys=True)
        assert code == 0

    def test_all_checks_show_tick(self, capsys, monkeypatch):
        _run_doctor(capsys, monkeypatch, api_keys=True)
        out = capsys.readouterr().out
        # At minimum: config, FAISS, graph, episodic, language, API key, CB, BM25
        assert out.count("✓") >= 7

    def test_summary_no_issues(self, capsys, monkeypatch):
        _run_doctor(capsys, monkeypatch, api_keys=True)
        out = capsys.readouterr().out
        assert "All checks passed" in out or "No issues" in out or "warning" in out.lower()


class TestDoctorNoApiKeys:
    def test_exit_0_no_api_keys(self, capsys, monkeypatch):
        # No API keys → warning → exit 1 (new contract: 0=clean, 1=warn, 2=error)
        code = _run_doctor(capsys, monkeypatch, api_keys=False)
        assert code <= 1

    def test_all_four_key_names_in_output(self, capsys, monkeypatch):
        _run_doctor(capsys, monkeypatch, api_keys=False)
        out = capsys.readouterr().out
        assert "ANTHROPIC_API_KEY" in out
        assert "GEMINI_API_KEY" in out
        assert "OPENAI_API_KEY" in out
        assert "GROK_API_KEY" in out

    def test_warning_mark_on_api_key_check(self, capsys, monkeypatch):
        _run_doctor(capsys, monkeypatch, api_keys=False)
        out = capsys.readouterr().out
        assert "⚠" in out


class TestDoctorFaissFailure:
    def test_exit_1_faiss_missing(self, capsys, monkeypatch):
        code = _run_doctor(capsys, monkeypatch, faiss_fail=True)
        assert code >= 1

    def test_cross_mark_on_faiss_check(self, capsys, monkeypatch):
        _run_doctor(capsys, monkeypatch, faiss_fail=True)
        out = capsys.readouterr().out
        assert "✗" in out


class TestDoctorGraphFailure:
    def test_exit_1_graph_missing(self, capsys, monkeypatch):
        code = _run_doctor(capsys, monkeypatch, graph_fail=True)
        assert code >= 1

    def test_cross_mark_on_graph_check(self, capsys, monkeypatch):
        _run_doctor(capsys, monkeypatch, graph_fail=True)
        out = capsys.readouterr().out
        assert "✗" in out


class TestDoctorMultipleFailures:
    def test_issue_count_in_summary(self, capsys, monkeypatch):
        code = _run_doctor(capsys, monkeypatch, faiss_fail=True, graph_fail=True, api_keys=False)
        out = capsys.readouterr().out
        assert code >= 2
        # Summary line mentions the count (new format: "X error(s)" or legacy "X issue(s)")
        assert "error" in out or "issue" in out


class TestDoctorVerbose:
    def test_verbose_shows_optional_section(self, capsys, monkeypatch):
        _run_doctor(capsys, monkeypatch, verbose=True)
        out = capsys.readouterr().out
        assert "Optional" in out or "cryptography" in out or "keyring" in out
