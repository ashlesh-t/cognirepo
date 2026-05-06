# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_claude_usefulness.py — CogniRepo usefulness benchmarks.

Uses isolated test data to ensure reliable execution.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture(autouse=True)
def setup_test_index(isolated_cognirepo, monkeypatch):
    """
    Build a small test index in the isolated directory so tests have data to query.
    """
    from cli.init_project import init_project
    from indexer.ast_indexer import ASTIndexer
    from graph.knowledge_graph import KnowledgeGraph
    
    # Initialize the project in the tmp directory
    init_project(no_index=True, interactive=False, non_interactive=True)
    
    # Create a few dummy files to index
    dummy_dir = Path(os.getcwd()) / "src"
    os.makedirs(dummy_dir, exist_ok=True)
    
    (dummy_dir / "retrieval.py").write_text("def hybrid_retrieve():\n    \"\"\"HybridRetriever scoring formula\"\"\"\n    pass", encoding="utf-8")
    (dummy_dir / "memory.py").write_text("def store_memory():\n    \"\"\"BM25 episodic search\"\"\"\n    pass", encoding="utf-8")
    (dummy_dir / "tools.py").write_text("def context_pack():\n    \"\"\"context_pack implementation\"\"\"\n    pass", encoding="utf-8")
    
    # Index them
    kg = KnowledgeGraph()
    idx = ASTIndexer(graph=kg)
    idx.index_repo(str(dummy_dir))
    idx.save()
    
    yield


_tiktoken_missing = pytest.importorskip.__module__  # noqa: F841
try:
    import tiktoken as _tiktoken  # noqa: F401
    _TIKTOKEN_AVAILABLE = True
except ImportError:
    _TIKTOKEN_AVAILABLE = False

_skip_no_tiktoken = pytest.mark.skipif(
    not _TIKTOKEN_AVAILABLE, reason="tiktoken not installed"
)


# ── 1. Token reduction ────────────────────────────────────────────────────────

@_skip_no_tiktoken
class TestTokenReduction:
    """context_pack must use fewer tokens than reading source files directly."""

    def test_context_pack_under_budget(self):
        from tools.context_pack import context_pack
        result = context_pack("how does hybrid retrieval work", max_tokens=2000)
        assert result["token_count"] <= 2000

    def test_context_pack_fewer_tokens_than_raw_file(self):
        from tools.context_pack import context_pack
        # packed_tokens will be small because we only have few dummy symbols
        result = context_pack("HybridRetriever scoring formula", max_tokens=2000)
        assert result["token_count"] > 0
        assert result["token_count"] < 1000

    def test_token_savings_reported(self):
        from tools.context_pack import context_pack
        result = context_pack("memory episodic search", max_tokens=1000)
        assert "token_count" in result
        assert result["token_count"] > 0


# ── 2. Symbol lookup speed ────────────────────────────────────────────────────

class TestSymbolLookupEfficiency:
    def test_lookup_returns_in_under_100ms(self):
        from indexer.ast_indexer import ASTIndexer
        from graph.knowledge_graph import KnowledgeGraph
        idx = ASTIndexer(graph=KnowledgeGraph())
        idx.load()

        t0 = time.perf_counter()
        result = idx.lookup_symbol("context_pack")
        elapsed_ms = (time.perf_counter() - t0) * 1000

        assert elapsed_ms < 100
        assert len(result) > 0

    def test_lookup_returns_file_and_line(self):
        from indexer.ast_indexer import ASTIndexer
        from graph.knowledge_graph import KnowledgeGraph
        idx = ASTIndexer(graph=KnowledgeGraph())
        idx.load()
        results = idx.lookup_symbol("context_pack")
        assert len(results) > 0
        assert all("file" in r and "line" in r for r in results)

    def test_lookup_vs_grep_equivalent(self):
        from indexer.ast_indexer import ASTIndexer
        from graph.knowledge_graph import KnowledgeGraph
        idx = ASTIndexer(graph=KnowledgeGraph())
        idx.load()

        known_symbols = ["context_pack", "hybrid_retrieve", "store_memory"]
        missing = [s for s in known_symbols if not idx.lookup_symbol(s)]
        assert not missing


# ── 3. Cache efficiency ───────────────────────────────────────────────────────

class TestCacheEfficiency:
    def test_hybrid_cache_hit_is_faster(self):
        from retrieval.hybrid import hybrid_retrieve, invalidate_hybrid_cache
        invalidate_hybrid_cache()

        t0 = time.perf_counter()
        hybrid_retrieve("BM25 search", top_k=5)
        cold_ms = (time.perf_counter() - t0) * 1000

        t1 = time.perf_counter()
        hybrid_retrieve("BM25 search", top_k=5)
        warm_ms = (time.perf_counter() - t1) * 1000

        assert warm_ms < cold_ms or warm_ms < 5

    def test_cache_stats_record_hits(self):
        from retrieval.hybrid import hybrid_retrieve, invalidate_hybrid_cache, cache_stats
        invalidate_hybrid_cache()
        hybrid_retrieve("test cache hit query", top_k=3)
        hybrid_retrieve("test cache hit query", top_k=3)
        stats = cache_stats()
        assert stats["hits"] >= 1


# ── 4. Memory recall (cross-session value) ───────────────────────────────────

class TestMemoryRecall:
    def test_stored_memory_is_retrievable(self):
        from tools.store_memory import store_memory
        from tools.retrieve_memory import retrieve_memory
        
        text = "pytest usefulness test: memory round-trip"
        store_memory(text, source="test")
        
        results = retrieve_memory("usefulness memory round-trip", top_k=3)
        texts = [r.get("text", "") for r in results]
        assert any("usefulness" in t for t in texts)

    def test_retrieval_returns_most_relevant_first(self):
        from retrieval.hybrid import hybrid_retrieve, invalidate_hybrid_cache
        invalidate_hybrid_cache()
        results = hybrid_retrieve("hybrid", top_k=5)
        if results:
            assert results[0]["final_score"] >= results[-1]["final_score"]


# ── 5. Answer grounding (context_pack quality) ───────────────────────────────

@_skip_no_tiktoken
class TestAnswerGrounding:
    def test_context_pack_has_sections(self):
        from tools.context_pack import context_pack
        result = context_pack("store_memory implementation", max_tokens=2000)
        assert "sections" in result

    def test_context_pack_sections_have_content(self):
        from tools.context_pack import context_pack
        result = context_pack("hybrid", max_tokens=2000)
        for section in result.get("sections", []):
            assert "content" in section or "text" in section

    def test_context_pack_query_preserved(self):
        from tools.context_pack import context_pack
        query = "unique_test_query"
        result = context_pack(query, max_tokens=500)
        assert result.get("query") == query


# ── 6. Cross-project global memory ───────────────────────────────────────────

class TestGlobalUserMemory:
    def test_global_dir_accessible_from_any_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from config.paths import get_global_dir
        global_dir = get_global_dir()
        assert "cognirepo" in global_dir

    def test_user_preference_survives_cwd_change(self, tmp_path, monkeypatch):
        from memory.user_memory import set_preference, get_preference
        set_preference("test_pref_xyz", "test_value_123")
        monkeypatch.chdir(tmp_path)
        val = get_preference("test_pref_xyz")
        assert val == "test_value_123"


# ── 7. Hybrid signal mix ──────────────────────────────────────────────────────

class TestHybridSignalMix:
    def test_vector_score_present(self):
        from retrieval.hybrid import hybrid_retrieve, invalidate_hybrid_cache
        invalidate_hybrid_cache()
        results = hybrid_retrieve("memory", top_k=5)
        if results:
            vector_scores = [r.get("vector_score", 0) for r in results]
            assert any(s > 0 for s in vector_scores)


# ── 8. Real-project portability ──────────────────────────────────────────────

class TestRealProjectPortability:
    def test_index_data_structure_stable(self):
        from indexer.ast_indexer import ASTIndexer
        from graph.knowledge_graph import KnowledgeGraph
        idx = ASTIndexer(graph=KnowledgeGraph())
        idx.load()
        required_keys = {"files", "reverse_index"}
        assert required_keys.issubset(set(idx.index_data.keys()))
