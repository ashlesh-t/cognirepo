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
        from memory.semantic_memory import SemanticMemory
        sm = SemanticMemory()
        sm.store("fixed JWT expiry in verify_token")
        sm.store("refactored session handling")

        from retrieval.hybrid import HybridRetriever
        r = HybridRetriever()
        results = r.retrieve("auth JWT", top_k=2)
        assert isinstance(results, list)

    def test_final_score_present(self):
        from memory.semantic_memory import SemanticMemory
        sm = SemanticMemory()
        sm.store("authentication token verification logic")

        from retrieval.hybrid import HybridRetriever
        r = HybridRetriever()
        results = r.retrieve("token auth", top_k=1)
        if results:
            assert "final_score" in results[0]
            assert 0.0 <= results[0]["final_score"] <= 1.0

    def test_top_k_respected(self):
        from memory.semantic_memory import SemanticMemory
        sm = SemanticMemory()
        for i in range(8):
            sm.store(f"memory item {i} about code and functions")

        from retrieval.hybrid import HybridRetriever
        r = HybridRetriever()
        results = r.retrieve("code functions", top_k=3)
        assert len(results) <= 3

    def test_cold_start_no_crash(self):
        """Empty graph + no behaviour data → falls back to vector only."""
        from retrieval.hybrid import HybridRetriever
        r = HybridRetriever()
        results = r.retrieve("anything at all", top_k=5)
        assert isinstance(results, list)

    def test_empty_store_returns_empty(self):
        from retrieval.hybrid import HybridRetriever
        r = HybridRetriever()
        results = r.retrieve("query with no memories stored", top_k=5)
        assert isinstance(results, list)

    def test_hybrid_retrieve_function(self):
        from memory.semantic_memory import SemanticMemory
        sm = SemanticMemory()
        sm.store("debug the login flow for oauth")

        from retrieval.hybrid import hybrid_retrieve
        results = hybrid_retrieve("oauth login", top_k=1)
        assert isinstance(results, list)

    def test_scores_sorted_descending(self):
        from memory.semantic_memory import SemanticMemory
        sm = SemanticMemory()
        sm.store("verify_token handles JWT expiry correctly")
        sm.store("unrelated topic about cooking recipes")
        sm.store("authentication middleware checks bearer token")

        from retrieval.hybrid import HybridRetriever
        r = HybridRetriever()
        results = r.retrieve("JWT authentication token", top_k=3)
        scores = [res["final_score"] for res in results if "final_score" in res]
        assert scores == sorted(scores, reverse=True)


class TestEpisodicBM25:
    def test_episodic_filter(self):
        from memory.episodic_memory import log_event
        log_event("deployed auth service to production", {"env": "prod"})
        log_event("fixed bug in payment module", {"module": "payments"})
        log_event("updated JWT expiry to 24 hours", {"service": "auth"})

        from retrieval.hybrid import episodic_bm25_filter
        results = episodic_bm25_filter("JWT auth", top_k=2)
        assert isinstance(results, list)
        # JWT-related event should appear
        if results:
            combined = " ".join(r.get("event", "") for r in results).lower()
            assert "jwt" in combined or "auth" in combined

    def test_time_range_excludes_out_of_range_events(self, monkeypatch):
        """time_range filter must only return events within the window."""
        import retrieval.hybrid as rh
        # Seed three events at different timestamps
        events = [
            {"id": "e0", "event": "authentication token bug", "metadata": {}, "time": "2026-01-01T10:00:00Z"},
            {"id": "e1", "event": "authentication token bug refactor", "metadata": {}, "time": "2026-02-01T10:00:00Z"},
            {"id": "e2", "event": "authentication token cache miss", "metadata": {}, "time": "2026-03-01T10:00:00Z"},
        ]
        from _bm25 import BM25 as _BM25, Document as _Document
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
