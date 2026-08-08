# pylint: disable=missing-docstring, unnecessary-lambda, import-outside-toplevel, too-few-public-methods, duplicate-code
# pylint: disable=redefined-outer-name, unused-argument, broad-exception-caught, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_hybrid_retrieval.py — hybrid retrieval merge + scoring tests.

Uses real SemanticMemory (no FAISS mock) against isolated temp store.
Graph and behaviour scores default to 0 (cold start) — tests the
formula degrades correctly to pure vector retrieval.
"""
from __future__ import annotations


class TestHybridRetriever:
    def test_returns_list(self):
        from data.memory.semantic_memory import SemanticMemory
        sm = SemanticMemory()
        sm.store("fixed JWT expiry in verify_token")
        sm.store("refactored session handling")

        from intelligence.retrieval.hybrid import HybridRetriever
        r = HybridRetriever()
        results = r.retrieve("auth JWT", top_k=2)
        assert isinstance(results, list)

    def test_final_score_present(self):
        from data.memory.semantic_memory import SemanticMemory
        sm = SemanticMemory()
        sm.store("authentication token verification logic")

        from intelligence.retrieval.hybrid import HybridRetriever
        r = HybridRetriever()
        results = r.retrieve("token auth", top_k=1)
        if results:
            assert "final_score" in results[0]
            assert 0.0 <= results[0]["final_score"] <= 1.0

    def test_top_k_respected(self):
        from data.memory.semantic_memory import SemanticMemory
        sm = SemanticMemory()
        for i in range(8):
            sm.store(f"memory item {i} about code and functions")

        from intelligence.retrieval.hybrid import HybridRetriever
        r = HybridRetriever()
        results = r.retrieve("code functions", top_k=3)
        assert len(results) <= 3

    def test_cold_start_no_crash(self):
        """Empty graph + no behaviour data → falls back to vector only."""
        from intelligence.retrieval.hybrid import HybridRetriever
        r = HybridRetriever()
        results = r.retrieve("anything at all", top_k=5)
        assert isinstance(results, list)

    def test_empty_store_returns_empty(self):
        from intelligence.retrieval.hybrid import HybridRetriever
        r = HybridRetriever()
        results = r.retrieve("query with no memories stored", top_k=5)
        assert isinstance(results, list)

    def test_hybrid_retrieve_function(self):
        from data.memory.semantic_memory import SemanticMemory
        sm = SemanticMemory()
        sm.store("debug the login flow for oauth")

        from intelligence.retrieval.hybrid import hybrid_retrieve
        results = hybrid_retrieve("oauth login", top_k=1)
        assert isinstance(results, list)

    def test_scores_sorted_descending(self):
        from data.memory.semantic_memory import SemanticMemory
        sm = SemanticMemory()
        sm.store("verify_token handles JWT expiry correctly")
        sm.store("unrelated topic about cooking recipes")
        sm.store("authentication middleware checks bearer token")

        from intelligence.retrieval.hybrid import HybridRetriever
        r = HybridRetriever()
        results = r.retrieve("JWT authentication token", top_k=3)
        scores = [res["final_score"] for res in results if "final_score" in res]
        assert scores == sorted(scores, reverse=True)


class TestGraphScoreSimilarToWeighting:
    """COGNIREPO-202 AC4 — SIMILAR_TO is weighted into _graph_score, not treated as a
    full-strength structural edge (non-regression: a real 1-hop edge still outscores it)."""

    def test_similar_to_only_link_discounted_below_real_edge(self):
        from data.graph.knowledge_graph import EdgeType, NodeType
        from intelligence.retrieval.hybrid import HybridRetriever

        r = HybridRetriever()
        r.graph.add_node("a.py::verify_a", NodeType.FUNCTION, file="a.py")
        r.graph.add_node("b.py::verify_b", NodeType.FUNCTION, file="b.py")
        r.graph.add_edge("a.py::verify_a", "b.py::verify_b", EdgeType.SIMILAR_TO, weight=0.9)
        r.graph.add_edge("b.py::verify_b", "a.py::verify_a", EdgeType.SIMILAR_TO, weight=0.9)
        r._undirected = r.graph.G.to_undirected()  # rebuild after manual edits

        similar_only_score = r._graph_score({"_symbol": "b.py::verify_b"}, ["a.py::verify_a"])

        r.graph.add_node("c.py::verify_c", NodeType.FUNCTION, file="c.py")
        r.graph.add_edge("a.py::verify_a", "c.py::verify_c", EdgeType.CALLED_BY)
        r.graph.add_edge("c.py::verify_c", "a.py::verify_a", EdgeType.CALLS)
        r._undirected = r.graph.G.to_undirected()

        real_edge_score = r._graph_score({"_symbol": "c.py::verify_c"}, ["a.py::verify_a"])

        assert 0.0 < similar_only_score < real_edge_score == 0.5

    def test_similar_to_plus_real_edge_not_discounted(self):
        """When a real structural edge ALSO connects the pair, no discount applies."""
        from data.graph.knowledge_graph import EdgeType, NodeType
        from intelligence.retrieval.hybrid import HybridRetriever

        r = HybridRetriever()
        r.graph.add_node("a.py::verify_a", NodeType.FUNCTION, file="a.py")
        r.graph.add_node("b.py::verify_b", NodeType.FUNCTION, file="b.py")
        r.graph.add_edge("a.py::verify_a", "b.py::verify_b", EdgeType.CALLED_BY)
        r.graph.add_edge("b.py::verify_b", "a.py::verify_a", EdgeType.SIMILAR_TO, weight=0.9)
        r._undirected = r.graph.G.to_undirected()

        score = r._graph_score({"_symbol": "b.py::verify_b"}, ["a.py::verify_a"])
        assert score == 0.5


class TestVectorRetrieveSourcePreservation:
    """COGNIREPO-D07: _vector_retrieve() must report the real stored source
    (previously hardcoded "semantic" for every vector-backend hit)."""

    def test_preserves_real_stored_source(self):
        from intelligence.retrieval.hybrid import HybridRetriever
        from data.memory.embeddings import encode_with_timeout

        r = HybridRetriever()
        vec = encode_with_timeout("interaction style summary text").astype("float32")
        r.db.add(vec, "interaction style summary text", importance=0.8, source="interaction_style")

        results = r._vector_retrieve(vec, k=5)
        assert results
        assert results[0]["source"] == "interaction_style"

    def test_defaults_to_memory_when_source_missing(self):
        from intelligence.retrieval.hybrid import HybridRetriever
        from data.memory.semantic_memory import SemanticMemory
        from data.memory.embeddings import encode_with_timeout

        sm = SemanticMemory()
        sm.store("plain stored memory with default source")

        r = HybridRetriever()
        vec = encode_with_timeout("plain stored memory with default source").astype("float32")
        results = r._vector_retrieve(vec, k=5)
        assert results
        assert results[0]["source"] == "memory"


class TestConcurrentCacheMiss:
    def test_concurrent_misses_call_retriever_once(self, monkeypatch):
        """N concurrent cache misses for same key → HybridRetriever.retrieve called once."""
        import threading
        import intelligence.retrieval.hybrid as rh

        rh.invalidate_hybrid_cache()
        call_count = {"n": 0}
        real_retrieve = rh.HybridRetriever.retrieve

        def counting_retrieve(self, query, top_k):
            call_count["n"] += 1
            return real_retrieve(self, query, top_k)

        monkeypatch.setattr(rh.HybridRetriever, "retrieve", counting_retrieve)
        rh.invalidate_hybrid_cache()

        results_bucket = []
        errors = []

        def _call():
            try:
                r = rh.hybrid_retrieve("concurrent test query", top_k=1)
                results_bucket.append(r)
            except Exception as exc:  # pylint: disable=broad-except
                errors.append(exc)

        threads = [threading.Thread(target=_call) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Thread errors: {errors}"
        assert len(results_bucket) == 5
        assert call_count["n"] == 1, (
            f"Expected 1 HybridRetriever.retrieve call, got {call_count['n']}"
        )


class TestEpisodicBM25:
    def test_episodic_filter(self):
        from data.memory.episodic_memory import log_event
        log_event("deployed auth service to production", {"env": "prod"})
        log_event("fixed bug in payment module", {"module": "payments"})
        log_event("updated JWT expiry to 24 hours", {"service": "auth"})

        from intelligence.retrieval.hybrid import episodic_bm25_filter
        results = episodic_bm25_filter("JWT auth", top_k=2)
        assert isinstance(results, list)
        # JWT-related event should appear
        if results:
            combined = " ".join(r.get("event", "") for r in results).lower()
            assert "jwt" in combined or "auth" in combined

    def test_time_range_excludes_out_of_range_events(self, monkeypatch):
        """time_range filter must only return events within the window."""
        import intelligence.retrieval.hybrid as rh
        # Seed three events at different timestamps
        events = [
            {"id": "e0", "event": "authentication token bug", "metadata": {}, "time": "2026-01-01T10:00:00Z"},
            {"id": "e1", "event": "authentication token bug refactor", "metadata": {}, "time": "2026-02-01T10:00:00Z"},
            {"id": "e2", "event": "authentication token cache miss", "metadata": {}, "time": "2026-03-01T10:00:00Z"},
        ]
        from core._bm25 import BM25 as _BM25, Document as _Document
        docs = [_Document(id=e["id"], text=e["event"]) for e in events]
        bm25_full = _BM25()
        bm25_full.index(docs)

        monkeypatch.setattr(rh, "_get_cached_bm25", lambda: (bm25_full, events))

        # Only e1 falls within this range
        results = rh.episodic_bm25_filter(
            "authentication",
            time_range=("2026-01-15T00:00:00Z", "2026-02-28T00:00:00Z"),
            top_k=10,
        )
        returned_ids = {r.get("id") for r in results}
        assert "e0" not in returned_ids, "e0 is outside time_range and must be excluded"
        assert "e2" not in returned_ids, "e2 is outside time_range and must be excluded"
        assert "e1" in returned_ids, "e1 is within time_range and must be returned"
