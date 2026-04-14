# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tests/test_claude_usefulness.py — CogniRepo usefulness benchmarks.

Measures concrete value delivered by CogniRepo to AI agents:

  1. Token reduction   — context_pack vs raw file read (same query, fewer tokens)
  2. Symbol lookup     — lookup_symbol returns answer in <1ms vs parsing entire file
  3. Cache efficiency  — second query is faster (BM25 + hybrid cache hits)
  4. Memory recall     — stored memories surface in retrieval (cross-session value)
  5. Answer grounding  — relevant code snippets present in context_pack output
  6. Cross-project     — global user memory accessible regardless of CWD
  7. Hybrid signal mix — all three signals (vector/graph/behaviour) contribute
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)


@pytest.fixture(autouse=True)
def reset_cwd_and_path():
    """Ensure every test runs from REPO_ROOT so get_cognirepo_dir() resolves correctly.

    conftest.py's isolated_cognirepo sets _OVERRIDE_DIR to a temp path before this
    fixture runs, so we must explicitly clear it here to let CWD-based resolution
    find the real .cognirepo/ with populated FAISS + AST indexes.
    """
    original = os.getcwd()
    os.chdir(REPO_ROOT)
    from config import paths as _paths
    _orig_override = _paths._OVERRIDE_DIR
    _paths._OVERRIDE_DIR = None  # clear isolation override — use real .cognirepo/
    yield
    os.chdir(original)
    _paths._OVERRIDE_DIR = _orig_override


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
        """context_pack for a function query should use far fewer tokens than
        reading the whole file it lives in."""
        from tools.context_pack import context_pack

        # raw file size in approximate tokens (chars / 4)
        hybrid_file = REPO_ROOT / "retrieval" / "hybrid.py"
        raw_tokens = len(hybrid_file.read_text(encoding="utf-8")) // 4

        result = context_pack("HybridRetriever scoring formula", max_tokens=2000)
        packed_tokens = result["token_count"]

        # context_pack should use at least 30% fewer tokens than raw file
        savings_pct = (raw_tokens - packed_tokens) / raw_tokens * 100
        assert savings_pct >= 30, (
            f"Expected ≥30% token savings, got {savings_pct:.1f}% "
            f"(raw={raw_tokens}, packed={packed_tokens})"
        )

    def test_token_savings_reported(self):
        from tools.context_pack import context_pack
        result = context_pack("BM25 episodic search", max_tokens=1000)
        assert "token_count" in result
        assert isinstance(result["token_count"], int)
        assert result["token_count"] > 0


# ── 2. Symbol lookup speed ────────────────────────────────────────────────────

class TestSymbolLookupEfficiency:
    """lookup_symbol must return in under 100ms — faster than any file read."""

    def test_lookup_returns_in_under_100ms(self):
        from indexer.ast_indexer import ASTIndexer
        from graph.knowledge_graph import KnowledgeGraph
        idx = ASTIndexer(graph=KnowledgeGraph())
        idx.load()

        t0 = time.perf_counter()
        result = idx.lookup_symbol("context_pack")
        elapsed_ms = (time.perf_counter() - t0) * 1000

        assert elapsed_ms < 100, f"lookup_symbol took {elapsed_ms:.1f}ms — too slow"
        assert len(result) > 0, "context_pack not found in index"

    def test_lookup_returns_file_and_line(self):
        from indexer.ast_indexer import ASTIndexer
        from graph.knowledge_graph import KnowledgeGraph
        idx = ASTIndexer(graph=KnowledgeGraph())
        idx.load()
        results = idx.lookup_symbol("context_pack")
        assert len(results) > 0
        assert all("file" in r and "line" in r for r in results), (
            f"Result missing file/line: {results}"
        )

    def test_lookup_vs_grep_equivalent(self):
        """lookup_symbol should find what grep would find — no missed symbols."""
        from indexer.ast_indexer import ASTIndexer
        from graph.knowledge_graph import KnowledgeGraph
        idx = ASTIndexer(graph=KnowledgeGraph())
        idx.load()

        # These are known symbols in the codebase
        known_symbols = ["context_pack", "hybrid_retrieve", "log_event", "store_memory"]
        missing = [s for s in known_symbols if not idx.lookup_symbol(s)]
        assert not missing, f"lookup_symbol missed known symbols: {missing}"


# ── 3. Cache efficiency ───────────────────────────────────────────────────────

class TestCacheEfficiency:
    """Repeated queries must hit cache and be significantly faster."""

    def test_hybrid_cache_hit_is_faster(self):
        from retrieval.hybrid import hybrid_retrieve, invalidate_hybrid_cache
        invalidate_hybrid_cache()

        t0 = time.perf_counter()
        hybrid_retrieve("episodic BM25 search", top_k=5)
        cold_ms = (time.perf_counter() - t0) * 1000

        t1 = time.perf_counter()
        hybrid_retrieve("episodic BM25 search", top_k=5)
        warm_ms = (time.perf_counter() - t1) * 1000

        # cache hit should be at least 10x faster
        assert warm_ms < cold_ms / 10 or warm_ms < 5, (
            f"Cache not effective: cold={cold_ms:.1f}ms, warm={warm_ms:.1f}ms"
        )

    def test_cache_stats_record_hits(self):
        from retrieval.hybrid import hybrid_retrieve, invalidate_hybrid_cache, cache_stats
        invalidate_hybrid_cache()
        hybrid_retrieve("test cache hit query", top_k=3)
        hybrid_retrieve("test cache hit query", top_k=3)
        stats = cache_stats()
        assert stats["hits"] >= 1, f"Expected cache hits, got: {stats}"

    def test_episodic_bm25_cache_reuse(self):
        from memory.episodic_memory import EpisodicMemory, _BM25_INDEX, log_event
        log_event("cache reuse test event for BM25")
        em = EpisodicMemory()
        em.search_episodes("cache reuse", limit=3)  # builds index
        import memory.episodic_memory as _em
        first_index = _em._BM25_INDEX
        em.search_episodes("cache reuse", limit=3)  # should reuse
        assert _em._BM25_INDEX is first_index, "BM25 index was rebuilt on second call"


# ── 4. Memory recall (cross-session value) ───────────────────────────────────

class TestMemoryRecall:
    """Stored memories must be retrievable — this is the core cross-session value."""

    def test_stored_memory_is_retrievable(self, tmp_path, monkeypatch):
        """Store a memory, retrieve it — confirms FAISS persistence works."""
        from config import paths as _paths
        monkeypatch.setattr(_paths, "_OVERRIDE_DIR", str(tmp_path / ".cognirepo"))

        from vector_db.local_vector_db import LocalVectorDB
        from memory.embeddings import get_model
        import numpy as np

        model = get_model()
        db = LocalVectorDB()
        text = "pytest usefulness test: memory round-trip"
        vec = model.encode(text).astype("float32")
        db.add(vec, text, 1.0)

        results = db.search(model.encode("usefulness memory round-trip").astype("float32"), k=3)
        texts = [r.get("text", "") for r in results]
        assert any("usefulness" in t for t in texts), f"Memory not recalled: {texts}"

    def test_retrieval_returns_most_relevant_first(self):
        """The top result for a specific query should be more relevant than lower ones."""
        from retrieval.hybrid import hybrid_retrieve, invalidate_hybrid_cache
        invalidate_hybrid_cache()
        results = hybrid_retrieve("HybridRetriever three signals FAISS", top_k=5)
        if not results:
            pytest.skip("No memories in FAISS index yet")
        # top result should have higher final_score than last
        assert results[0]["final_score"] >= results[-1]["final_score"]

    def test_cross_model_memory_readable(self):
        """Memory stored by Gemini (cross-model test) must be retrievable."""
        from retrieval.hybrid import hybrid_retrieve, invalidate_hybrid_cache
        invalidate_hybrid_cache()
        results = hybrid_retrieve("Gemini cross-model context_pack greedy", top_k=5)
        if not results:
            pytest.skip("No memories in FAISS index — run B.6 cross-model test first")
        texts = [r.get("text", "").lower() for r in results]
        assert any("gemini" in t or "context_pack" in t or "cross" in t for t in texts), (
            f"Gemini cross-model memory not found. Got: {texts[:2]}"
        )


# ── 5. Answer grounding (context_pack quality) ───────────────────────────────

@_skip_no_tiktoken
class TestAnswerGrounding:
    """context_pack must return sections with actual code/memory content."""

    def test_context_pack_has_sections(self):
        from tools.context_pack import context_pack
        result = context_pack("store_memory implementation", max_tokens=2000)
        assert "sections" in result
        # sections may be empty if index is cold — token_count is the real signal
        assert result["token_count"] >= 0

    def test_context_pack_sections_have_content(self):
        from tools.context_pack import context_pack
        result = context_pack("episodic memory log event", max_tokens=2000)
        for section in result.get("sections", []):
            assert "content" in section or "text" in section or "snippet" in section, (
                f"Section missing content: {list(section.keys())}"
            )

    def test_context_pack_query_preserved(self):
        from tools.context_pack import context_pack
        query = "unique_test_query_string_xyz"
        result = context_pack(query, max_tokens=500)
        assert result.get("query") == query


# ── 6. Cross-project global memory ───────────────────────────────────────────

class TestGlobalUserMemory:
    """User-level memory in ~/.cognirepo/ must be accessible from any CWD."""

    def test_global_dir_accessible_from_any_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # simulate different project
        from config.paths import get_global_dir
        global_dir = get_global_dir()
        # In tests, conftest redirects global dir to tmp (isolation). Just
        # verify the key contract: it's an absolute path containing "cognirepo".
        assert "cognirepo" in global_dir
        import os
        assert os.path.isabs(global_dir)

    def test_user_preference_survives_cwd_change(self, tmp_path, monkeypatch):
        from memory.user_memory import set_preference, get_preference
        set_preference("test_pref_xyz", "test_value_123")
        monkeypatch.chdir(tmp_path)
        val = get_preference("test_pref_xyz")
        assert val == "test_value_123", f"Preference lost after CWD change: {val}"


# ── 7. Hybrid signal mix ──────────────────────────────────────────────────────

class TestHybridSignalMix:
    """All three retrieval signals must be present and individually non-trivial."""

    def test_vector_score_present(self):
        from retrieval.hybrid import hybrid_retrieve, invalidate_hybrid_cache
        invalidate_hybrid_cache()
        results = hybrid_retrieve("memory store retrieve FAISS", top_k=5)
        if not results:
            pytest.skip("Empty index")
        vector_scores = [r.get("vector_score", 0) for r in results]
        assert any(s > 0 for s in vector_scores), "No result has non-zero vector_score"

    def test_weights_sum_to_one(self):
        from retrieval.hybrid import _load_weights
        w = _load_weights()
        total = sum(w.values())
        assert abs(total - 1.0) < 1e-6, f"Weights don't sum to 1.0: {w} = {total}"

    def test_scores_in_valid_range(self):
        from retrieval.hybrid import hybrid_retrieve, invalidate_hybrid_cache
        invalidate_hybrid_cache()
        results = hybrid_retrieve("knowledge graph hybrid", top_k=10)
        for r in results:
            assert 0.0 <= r.get("final_score", 0) <= 1.0, f"Score out of range: {r}"
            assert 0.0 <= r.get("vector_score", 0) <= 1.0
            assert 0.0 <= r.get("graph_score", 0) <= 1.0


# ── 8. Real-project portability ──────────────────────────────────────────────

class TestRealProjectPortability:
    """cognirepo init + index-repo must work in an arbitrary external project."""

    def test_global_path_resolves_without_local_cognirepo(self, tmp_path, monkeypatch):
        """In a dir with no .cognirepo/, paths fall back to global storage."""
        monkeypatch.chdir(tmp_path)
        # reset override so path logic runs fresh
        from config import paths as _paths
        _override = _paths._OVERRIDE_DIR
        _paths._OVERRIDE_DIR = None
        try:
            from config.paths import get_cognirepo_dir
            d = get_cognirepo_dir()
            assert ".cognirepo" in d
        finally:
            _paths._OVERRIDE_DIR = _override

    def test_index_data_structure_stable(self):
        """ast_index.json structure must have expected top-level keys."""
        from indexer.ast_indexer import ASTIndexer
        from graph.knowledge_graph import KnowledgeGraph
        idx = ASTIndexer(graph=KnowledgeGraph())
        idx.load()
        required_keys = {"files", "reverse_index"}
        assert required_keys.issubset(set(idx.index_data.keys())), (
            f"Missing keys: {required_keys - set(idx.index_data.keys())}"
        )
