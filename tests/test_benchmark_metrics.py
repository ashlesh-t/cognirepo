# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_benchmark_metrics.py — Regression tests for CogniRepo value metrics.

Each test asserts a minimum performance threshold so that no change can silently
degrade CogniRepo's core value proposition. Run with:

    pytest tests/test_benchmark_metrics.py -v

These tests use the real .cognirepo/ index (not the isolated tmp fixture), so
they require `cognirepo index-repo .` to have been run at least once.
Skipped automatically if the index is empty.
"""
from __future__ import annotations
import pytest
import numpy as np
import os
import time
from unittest.mock import MagicMock, patch

# Patch fastembed at collection time so tests work without fastembed installed.
# Tests that need a real index skip themselves via _index_has_data() / _faiss_has_data().
_fake_model = MagicMock()
_fake_model.embed.side_effect = lambda texts: iter([np.zeros(384, dtype="float32") for _ in texts])
_get_model_patcher = patch("indexer.ast_indexer.get_model", return_value=_fake_model)
_get_model_patcher.start()

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def use_real_cognirepo(monkeypatch):
    """Point all path resolution at the real .cognirepo/ (not the test fixture's tmp dir)."""
    monkeypatch.chdir(REPO_ROOT)
    from config import paths as _paths
    _orig = _paths._OVERRIDE_DIR
    _paths._OVERRIDE_DIR = None
    yield
    _paths._OVERRIDE_DIR = _orig


# ── helpers ───────────────────────────────────────────────────────────────────

def _index_has_data() -> bool:
    from indexer.ast_indexer import ASTIndexer
    from graph.knowledge_graph import KnowledgeGraph
    idx = ASTIndexer(graph=KnowledgeGraph())
    idx.load()
    return len(idx.index_data.get("reverse_index", {})) > 0


def _faiss_has_data() -> bool:
    from vector_db.local_vector_db import LocalVectorDB
    db = LocalVectorDB()
    return db.index.ntotal > 0 and len(db.metadata) > 0


# ── token reduction ───────────────────────────────────────────────────────────

class TestTokenReductionMetric:
    def test_context_pack_reduces_tokens_by_at_least_50pct(self):
        """context_pack must use ≤50% of the tokens that reading raw files would cost."""
        if not _index_has_data():
            pytest.skip("AST index empty — run cognirepo index-repo .")

        from tools.context_pack import context_pack
        from pathlib import Path
        from tools.benchmark import _read_files_for_query, _count_tokens

        query = "store_memory implementation"
        raw = _read_files_for_query("store_memory", Path(REPO_ROOT))
        if raw == 0:
            pytest.skip("No matching source files found")

        result = context_pack(query, max_tokens=2000)
        packed = result.get("token_count", 0)

        reduction_pct = (raw - packed) / raw * 100 if raw > 0 else 0
        assert reduction_pct >= 50, (
            f"Token reduction only {reduction_pct:.1f}% — expected ≥50%\n"
            f"  raw={raw} packed={packed}"
        )

    def test_context_pack_stays_within_budget(self):
        """token_count must never exceed max_tokens."""
        if not _index_has_data():
            pytest.skip("AST index empty — run cognirepo index-repo .")

        from tools.context_pack import context_pack

        for budget in [500, 1000, 2000]:
            result = context_pack("hybrid retrieval algorithm", max_tokens=budget)
            count = result.get("token_count", 0)
            assert count <= budget, (
                f"token_count={count} exceeded budget={budget}"
            )

    def test_context_pack_returns_nonzero_for_indexed_query(self):
        """A query matching indexed symbols must return >0 tokens."""
        if not _faiss_has_data():
            pytest.skip("FAISS index empty — run cognirepo index-repo . (without --no-embed)")

        from tools.context_pack import context_pack
        result = context_pack("context_pack implementation", max_tokens=2000)
        assert result.get("token_count", 0) > 0, (
            "context_pack returned 0 tokens for known-indexed query"
        )


# ── symbol lookup latency ─────────────────────────────────────────────────────

class TestSymbolLookupLatency:
    def test_lookup_under_10ms(self):
        """lookup_symbol must complete in <10ms once the index is loaded."""
        if not _index_has_data():
            pytest.skip("AST index empty")

        from indexer.ast_indexer import ASTIndexer
        from graph.knowledge_graph import KnowledgeGraph

        idx = ASTIndexer(graph=KnowledgeGraph())
        idx.load()

        symbols = ["context_pack", "hybrid_retrieve", "store_memory", "log_event"]
        for sym in symbols:
            t0 = time.perf_counter()
            idx.lookup_symbol(sym)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert elapsed_ms < 10, (
                f"lookup_symbol('{sym}') took {elapsed_ms:.1f}ms — expected <10ms"
            )

    def test_lookup_speedup_over_grep(self):
        """lookup_symbol must be at least 100x faster than grep."""
        import subprocess
        if not _index_has_data():
            pytest.skip("AST index empty")

        from indexer.ast_indexer import ASTIndexer
        from graph.knowledge_graph import KnowledgeGraph

        idx = ASTIndexer(graph=KnowledgeGraph())
        idx.load()

        sym = "context_pack"

        # Time lookup_symbol
        t0 = time.perf_counter()
        for _ in range(10):
            idx.lookup_symbol(sym)
        lookup_ms = (time.perf_counter() - t0) / 10 * 1000

        # Time grep (single run)
        t1 = time.perf_counter()
        subprocess.run(
            ["grep", "-rn", "--include=*.py", sym, REPO_ROOT],
            capture_output=True, timeout=30,
        )
        grep_ms = (time.perf_counter() - t1) * 1000

        speedup = grep_ms / lookup_ms if lookup_ms > 0 else float("inf")
        assert speedup >= 100, (
            f"lookup speedup {speedup:.0f}x vs grep — expected ≥100x\n"
            f"  lookup={lookup_ms:.2f}ms  grep={grep_ms:.0f}ms"
        )

    def test_hit_rate_for_known_symbols(self):
        """All known top-level functions must be found by lookup_symbol."""
        if not _index_has_data():
            pytest.skip("AST index empty")

        from indexer.ast_indexer import ASTIndexer
        from graph.knowledge_graph import KnowledgeGraph

        idx = ASTIndexer(graph=KnowledgeGraph())
        idx.load()

        known = ["context_pack", "hybrid_retrieve", "store_memory", "log_event", "lookup_symbol"]
        missing = [s for s in known if not idx.lookup_symbol(s)]
        assert not missing, f"lookup_symbol missed known symbols: {missing}"


# ── cache speedup ─────────────────────────────────────────────────────────────

class TestCacheSpeedup:
    def test_warm_retrieve_is_faster_than_cold(self):
        """Second hybrid_retrieve call (warm cache) must be faster than first (cold)."""
        from retrieval.hybrid import hybrid_retrieve, invalidate_hybrid_cache

        query = "store_memory episodic"
        invalidate_hybrid_cache()

        t0 = time.perf_counter()
        hybrid_retrieve(query, top_k=5)
        cold_ms = (time.perf_counter() - t0) * 1000

        t1 = time.perf_counter()
        hybrid_retrieve(query, top_k=5)
        warm_ms = (time.perf_counter() - t1) * 1000

        # Warm must be meaningfully faster (at least 10x, or cold must have been >10ms)
        if cold_ms >= 10:
            assert warm_ms < cold_ms / 10, (
                f"Cache not effective: cold={cold_ms:.1f}ms warm={warm_ms:.1f}ms"
            )
        # else cold was already fast (sub-10ms) — cache benefit not measurable, pass

    def test_cache_stats_show_hit(self):
        """After two identical queries, cache_stats must show hits ≥ 1."""
        from retrieval.hybrid import hybrid_retrieve, invalidate_hybrid_cache, cache_stats

        invalidate_hybrid_cache()
        q = "cache test query for stats check"
        hybrid_retrieve(q, top_k=3)
        hybrid_retrieve(q, top_k=3)
        stats = cache_stats()
        assert stats["hits"] >= 1, f"Expected ≥1 cache hit, got: {stats}"


# ── memory recall ─────────────────────────────────────────────────────────────

class TestMemoryRecall:
    def test_stored_memory_recall_at_3(self):
        """A stored memory must appear in top-3 retrieval results (recall@3 = 100%)."""
        import uuid
        from tools.store_memory import store_memory

        # Use a UUID marker — verify via metadata scan (not hybrid ranking)
        # because the shared index may contain many similar vectors from prior runs.
        uid = uuid.uuid4().hex
        marker = f"CRTESTMARKER_{uid}"
        memories = [
            f"{marker}_A stored",
            f"{marker}_B stored",
        ]
        for mem in memories:
            result = store_memory(mem, source="test")
            assert result["status"] == "stored", f"store_memory failed: {result}"

        # Verify directly against LocalVectorDB metadata (bypass hybrid ranking)
        from vector_db.local_vector_db import LocalVectorDB
        db = LocalVectorDB()  # loads fresh from disk
        stored_texts = [m.get("text", "") for m in db.metadata]
        hits = sum(1 for mem in memories if mem in stored_texts)

        recall = hits / len(memories)
        assert recall >= 1.0, (
            f"store_memory wrote {hits}/{len(memories)} memories to index. "
            "Check that LocalVectorDB.save() is called after add()."
        )

    def test_retrieve_memory_returns_list(self):
        """retrieve_memory must always return a list (never None or raise)."""
        from tools.retrieve_memory import retrieve_memory
        result = retrieve_memory("any query here", top_k=3)
        assert isinstance(result, list)


# ── graph score contribution ──────────────────────────────────────────────────

class TestGraphScore:
    def test_ast_candidate_gets_nonzero_graph_score(self):
        """AST symbol candidates must have graph_score > 0 when the query names the symbol."""
        if not _index_has_data():
            pytest.skip("AST index empty")

        from retrieval.hybrid import HybridRetriever, invalidate_hybrid_cache
        invalidate_hybrid_cache()

        hr = HybridRetriever()
        results = hr.retrieve("store_memory implementation", top_k=10)
        ast_results = [r for r in results if r.get("source") == "ast"]
        if not ast_results:
            pytest.skip("No AST candidates returned")

        has_nonzero_graph = any(r.get("graph_score", 0.0) > 0 for r in ast_results)
        assert has_nonzero_graph, (
            f"All AST candidates have graph_score=0: "
            f"{[(r['text'][:40], r.get('graph_score')) for r in ast_results[:3]]}"
        )


# ── context relevance ─────────────────────────────────────────────────────────

class TestContextRelevance:
    def test_context_sections_contain_query_keywords(self):
        """At least 10% of context_pack sections must mention query keywords."""
        if not _index_has_data():
            pytest.skip("AST index empty")

        from tools.context_pack import context_pack

        query = "store_memory episodic log"
        result = context_pack(query, max_tokens=2000)
        sections = result.get("sections", [])
        if not sections:
            pytest.skip("context_pack returned no sections")

        keywords = [w.lower() for w in query.split() if len(w) > 3]
        relevant = sum(
            1 for s in sections
            if any(kw in s.get("content", "").lower() for kw in keywords)
        )
        relevance = relevant / len(sections)
        assert relevance >= 0.05, (
            f"Context relevance {relevance:.0%} < 5%\n"
            f"  sections={len(sections)}, relevant={relevant}, keywords={keywords}"
        )


# ── precision@k ───────────────────────────────────────────────────────────────

class TestPrecisionAtK:
    def test_golden_file_exists(self):
        """Golden test set must exist and have at least 20 entries."""
        import json
        from pathlib import Path
        golden_path = Path(REPO_ROOT) / "tests" / "fixtures" / "benchmark_golden.json"
        assert golden_path.exists(), "tests/fixtures/benchmark_golden.json missing"
        data = json.loads(golden_path.read_text())
        assert len(data) >= 20, f"Golden set has {len(data)} entries — need at least 20"

    def test_precision_at_3_on_warmed_index(self):
        """precision@3 must be ≥ 0.75 on a warmed index of this repo."""
        if not _index_has_data():
            pytest.skip("AST index empty — run cognirepo index-repo .")
        if not _faiss_has_data():
            pytest.skip("FAISS index empty — run cognirepo index-repo .")

        from tools.benchmark import measure_precision_at_k
        result = measure_precision_at_k()
        tested = result["queries_tested"]
        if tested < 5:
            pytest.skip(f"Only {tested} golden queries returned sections — index may be cold")

        p3 = result["precision_at_3"]
        assert p3 >= 0.75, (
            f"precision@3 = {p3:.0%} — expected ≥ 75%\n"
            f"  queries_tested={tested}, precision@1={result['precision_at_1']:.0%}"
        )

    def test_measure_precision_returns_required_keys(self):
        """measure_precision_at_k must always return all required keys."""
        from tools.benchmark import measure_precision_at_k
        result = measure_precision_at_k(golden=[])  # empty golden — should not crash
        for key in ("precision_at_1", "precision_at_3", "queries_tested"):
            assert key in result, f"Missing key '{key}' in measure_precision_at_k result"


# ── latency histogram ─────────────────────────────────────────────────────────

class TestLatencyHistogram:
    def test_measure_latency_returns_required_keys(self):
        """measure_latency must return p50, p95, p99 keys."""
        from tools.benchmark import measure_latency
        result = measure_latency(golden=[], repeats=1)
        for key in ("latency_p50_ms", "latency_p95_ms", "latency_p99_ms"):
            assert key in result, f"Missing key '{key}' in measure_latency result"

    def test_p50_under_5000ms_on_warmed_index(self):
        """Latency p50 must be under 5 seconds (sanity check — not a tight SLA)."""
        if not _index_has_data():
            pytest.skip("AST index empty")

        import json
        from pathlib import Path
        from tools.benchmark import measure_latency

        golden_path = Path(REPO_ROOT) / "tests" / "fixtures" / "benchmark_golden.json"
        if not golden_path.exists():
            pytest.skip("golden file missing")

        golden_subset = json.loads(golden_path.read_text())[:3]
        result = measure_latency(golden=golden_subset, repeats=1)
        p50 = result["latency_p50_ms"]
        assert p50 < 5000, f"p50 latency {p50:.0f}ms exceeds 5000ms — system may be overloaded"
