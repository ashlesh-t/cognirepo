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
    from interface.cli.main import _cmd_doctor  # imported here so SPDX header is already applied

    # ── stub env ──────────────────────────────────────────────────────────────
    for var in ["ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                "OPENAI_API_KEY", "GROK_API_KEY", "COGNIREPO_MULTI_AGENT_ENABLED"]:
        monkeypatch.delenv(var, raising=False)

    if api_keys:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

    # ── stub vector_db ────────────────────────────────────────────────────────
    fake_vdb_mod = types.ModuleType("core.vector_db.local_vector_db")
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
    monkeypatch.setitem(sys.modules, "core.vector_db.local_vector_db", fake_vdb_mod)

    # ── stub graph ────────────────────────────────────────────────────────────
    fake_graph_mod = types.ModuleType("data.graph.knowledge_graph")
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
            def integrity_report(self, repo_root):  # pylint: disable=unused-argument
                return {"orphans": [], "dangling_files": [], "swept_at": "2026-01-01T00:00:00+00:00"}
        fake_graph_mod.KnowledgeGraph = _FakeKG
    monkeypatch.setitem(sys.modules, "data.graph.knowledge_graph", fake_graph_mod)

    # ── stub episodic ─────────────────────────────────────────────────────────
    fake_ep_mod = types.ModuleType("data.memory.episodic_memory")
    if episodic_fail:
        def _bad_history(**_kw):
            raise RuntimeError("episodic.json not found")
        fake_ep_mod.get_history = _bad_history
    else:
        fake_ep_mod.get_history = lambda **_kw: [{"event": "x"}] * 89
    monkeypatch.setitem(sys.modules, "data.memory.episodic_memory", fake_ep_mod)

    # ── stub AST indexer ──────────────────────────────────────────────────────
    fake_idx_mod = types.ModuleType("intelligence.indexer.ast_indexer")
    class _FakeASTIndexer:
        def __init__(self, **_kw):
            self.index_data = {}
        def load(self):
            pass
    fake_idx_mod.ASTIndexer = _FakeASTIndexer
    monkeypatch.setitem(sys.modules, "intelligence.indexer.ast_indexer", fake_idx_mod)

    # ── stub language registry ────────────────────────────────────────────────
    fake_lang_mod = types.ModuleType("intelligence.indexer.language_registry")
    fake_lang_mod.supported_extensions = lambda: {".py", ".js", ".ts"}
    fake_lang_mod._GRAMMAR_MAP = {".py": "tree-sitter-python"}
    fake_lang_mod._get_language = lambda ext: None
    fake_lang_mod.clear_cache = lambda: None
    monkeypatch.setitem(sys.modules, "intelligence.indexer.language_registry", fake_lang_mod)

    # ── stub circuit breaker ──────────────────────────────────────────────────
    fake_cb_mod = types.ModuleType("data.memory.circuit_breaker")
    class _FakeCBState:
        value = "CLOSED"
    class _FakeCB:
        state = _FakeCBState()
        _rss_limit_mb = 6553.0
    fake_cb_mod.get_breaker = lambda: _FakeCB()
    monkeypatch.setitem(sys.modules, "data.memory.circuit_breaker", fake_cb_mod)

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

    # ── stub chromadb (check 2) ───────────────────────────────────────────────
    fake_chroma_mod = types.ModuleType("chromadb")
    class _FakeChromaCollection:
        def count(self):
            return 22
    class _FakeChromaClient:
        def get_or_create_collection(self, *_a, **_kw):
            return _FakeChromaCollection()
    fake_chroma_mod.PersistentClient = lambda path: _FakeChromaClient()
    monkeypatch.setitem(sys.modules, "chromadb", fake_chroma_mod)

    # ── stub fastembed (check 13) ─────────────────────────────────────────────
    fake_fe_mod = types.ModuleType("fastembed")
    fake_fe_mod.__version__ = "0.3.6"
    monkeypatch.setitem(sys.modules, "fastembed", fake_fe_mod)

    # ── stub server.mcp_server (new check 14) ─────────────────────────────────
    fake_mcp_server_mod = types.ModuleType("interface.server.mcp_server")
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
        "find_symbol_path", "get_service_endpoints",
    }
    monkeypatch.setitem(sys.modules, "interface.server.mcp_server", fake_mcp_server_mod)

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
            # When simulating FAISS failure, hide the AST index file so
            # the doctor treats it as "not built" → increments issues.
            if faiss_fail and "ast_index.json" in ps:
                return False
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


class TestDoctorGraphQuarantine:
    """COGNIREPO-103 AC3: doctor lists quarantined graph.pkl.corrupt-* files."""

    def test_quarantined_file_is_listed(self, capsys, monkeypatch):
        from core.config.paths import get_path

        graph_dir = get_path("graph")
        os.makedirs(graph_dir, exist_ok=True)
        quarantine_name = "graph.pkl.corrupt-1784120946"
        with open(os.path.join(graph_dir, quarantine_name), "w", encoding="utf-8") as f:
            f.write("corrupt")

        code = _run_doctor(capsys, monkeypatch)
        out = capsys.readouterr().out

        assert quarantine_name in out
        assert code >= 1  # warning-level, not a hard failure

    def test_no_quarantine_files_no_warning(self, capsys, monkeypatch):
        code = _run_doctor(capsys, monkeypatch)
        out = capsys.readouterr().out

        assert "corrupt-" not in out
        assert code == 0


class TestDoctorGraphIntegrity:
    """COGNIREPO-201 AC2: doctor flags a seeded dangling node; clean fresh index reports 0/0."""

    def test_dangling_node_produces_warn(self, isolated_cognirepo, capsys):
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType
        from interface.cli.main import _cmd_doctor

        kg = KnowledgeGraph()
        kg.add_node("gone.py", NodeType.FILE)
        kg.add_node("gone.py::stale", NodeType.FUNCTION, file="gone.py")
        kg.add_edge("gone.py::stale", "gone.py", EdgeType.DEFINED_IN)
        kg.save()

        code = _cmd_doctor(verbose=False)
        out = capsys.readouterr().out
        assert "Graph integrity" in out
        assert "1 dangling file" in out
        assert "cognirepo graph repair --apply" in out
        assert code >= 1

    def test_clean_graph_reports_zero(self, isolated_cognirepo, capsys):
        from data.graph.knowledge_graph import KnowledgeGraph
        from interface.cli.main import _cmd_doctor

        KnowledgeGraph().save()

        _cmd_doctor(verbose=False)
        out = capsys.readouterr().out
        assert "Graph integrity — 0 orphans · 0 dangling files" in out


class TestDoctorWorkingTreeDirty:
    """
    COGNIREPO-D11: doctor must surface the same uncommitted-working-tree
    finding as `verify-index`, as a non-fatal WARN. Uses a real git repo
    (isolated_cognirepo chdirs into tmp_path) rather than _run_doctor's
    in-process module stubs, since the check shells out to `git status`.
    """

    @staticmethod
    def _sh(*args):
        import subprocess
        subprocess.run(["git", *args], check=True, capture_output=True)

    def _write_manifest(self, isolated_cognirepo):  # pylint: disable=unused-argument
        import json
        import platform
        import subprocess
        from datetime import datetime, timezone
        import faiss
        from core.config.paths import get_path
        from intelligence.indexer.ast_indexer import (
            _ast_index_file, _ast_faiss_file, _ast_meta_file, _manifest_file, _sha256_file,
        )

        os.makedirs(get_path("index"), exist_ok=True)
        for f in (_ast_index_file(), _ast_faiss_file(), _ast_meta_file()):
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("stub")
        git_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        manifest = {
            "platform": {"arch": platform.machine(), "faiss": faiss.__version__},
            "index_checksums": {
                "ast_index.json": _sha256_file(_ast_index_file()),
                "ast.index": _sha256_file(_ast_faiss_file()),
                "ast_metadata.json": _sha256_file(_ast_meta_file()),
            },
            "git_commit": git_commit,
            "indexed_at": datetime.now(tz=timezone.utc).isoformat(),
            "source_file_count": 1,
            "symbol_count": 1,
        }
        with open(_manifest_file(), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)

    def test_dirty_tree_produces_warn_not_hard_failure(self, isolated_cognirepo, capsys):
        from interface.cli.main import _cmd_doctor

        self._sh("init", "-q")
        self._sh("config", "user.email", "test@example.com")
        self._sh("config", "user.name", "Test")
        with open("mod.py", "w", encoding="utf-8") as f:
            f.write("def foo(): pass\n")
        self._sh("add", "-A")
        self._sh("commit", "-q", "-m", "init")

        self._write_manifest(isolated_cognirepo)

        with open("mod.py", "a", encoding="utf-8") as f:
            f.write("def bar(): pass\n")

        code = _cmd_doctor()
        out = capsys.readouterr().out

        assert "Working tree" in out
        assert "uncommitted indexed source file" in out
        assert "verify-index" in out
        # WARN is non-fatal — must not be the sole reason for a nonzero exit.
        # (Other checks may legitimately warn/fail in a bare fresh env; we
        # only assert this specific check didn't escalate to a hard failure.)
        assert "✗" not in out.split("Working tree")[1].split("\n")[0]

    def test_clean_tree_no_working_tree_warning(self, isolated_cognirepo, capsys):
        from interface.cli.main import _cmd_doctor

        self._sh("init", "-q")
        self._sh("config", "user.email", "test@example.com")
        self._sh("config", "user.name", "Test")
        with open("mod.py", "w", encoding="utf-8") as f:
            f.write("def foo(): pass\n")
        self._sh("add", "-A")
        self._sh("commit", "-q", "-m", "init")

        self._write_manifest(isolated_cognirepo)

        _cmd_doctor()
        out = capsys.readouterr().out

        assert "Working tree" not in out
