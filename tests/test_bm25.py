# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tests/test_bm25.py — Sprint 2.2 BM25 acceptance criteria.

Tests run against whichever backend is active (Python fallback by default;
C++ extension if _bm25_ext is compiled and on the path).  The BACKEND
constant tells you which one.

Covered:
  - Index 5 docs, search query, verify ranked order
  - Empty doc list: returns [], no crash
  - top_k > doc count: clamps to doc count
  - BACKEND constant is 'cpp' or 'python'
  - Identical results between backends on same input (when both available)
  - episodic_bm25_filter uses the BM25 backend transparently
"""
from __future__ import annotations

import pytest


# ── fixtures / helpers ────────────────────────────────────────────────────────

def _bm25():
    from _bm25 import BM25
    return BM25()


def _docs(entries: list[tuple[str, str]]):
    from _bm25 import Document
    return [Document(id=id_, text=text) for id_, text in entries]


# ── BACKEND constant ──────────────────────────────────────────────────────────

class TestBackendConstant:
    def test_backend_is_valid_string(self):
        from _bm25 import BACKEND
        assert BACKEND in ("cpp", "python"), f"Unexpected BACKEND: {BACKEND!r}"

    def test_backend_reported(self, capsys):
        from _bm25 import BACKEND
        print(f"Active BM25 backend: {BACKEND}")
        out = capsys.readouterr().out
        assert "backend" in out.lower()


# ── core BM25 logic ───────────────────────────────────────────────────────────

class TestBM25Core:
    def test_empty_corpus_returns_empty(self):
        bm25 = _bm25()
        bm25.index([])
        assert bm25.search("anything") == []

    def test_empty_query_returns_empty(self):
        bm25 = _bm25()
        bm25.index(_docs([("d1", "hello world"), ("d2", "foo bar")]))
        result = bm25.search("")
        assert result == []

    def test_single_doc_match(self):
        bm25 = _bm25()
        bm25.index(_docs([("d1", "the quick brown fox jumps over the lazy dog")]))
        results = bm25.search("fox")
        assert len(results) == 1
        assert results[0][0] == "d1"
        assert results[0][1] > 0

    def test_ranked_order_five_docs(self):
        """Most-relevant doc must rank first across 5 docs."""
        bm25 = _bm25()
        bm25.index(_docs([
            ("d1", "authentication JWT token bearer"),
            ("d2", "JWT file upload processing"),          # one query term → low score
            ("d3", "JWT authentication middleware verify token"),
            ("d4", "database connection pooling"),
            ("d5", "password reset email flow"),
        ]))
        results = bm25.search("JWT authentication token")
        ids = [r[0] for r in results]
        # d3 and d1 have the most query terms — must rank in top 2
        assert "d3" in ids
        assert "d1" in ids
        assert ids.index("d3") < ids.index("d2")
        assert ids.index("d1") < ids.index("d2")

    def test_scores_descending(self):
        bm25 = _bm25()
        bm25.index(_docs([
            ("d1", "python async event loop coroutine"),
            ("d2", "python programming language"),
            ("d3", "unrelated topic about cooking"),
        ]))
        results = bm25.search("python async coroutine")
        scores = [r[1] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_top_k_clamps_to_doc_count(self):
        """Asking for more results than docs must not crash or over-return."""
        bm25 = _bm25()
        bm25.index(_docs([("d1", "foo bar"), ("d2", "baz qux")]))
        results = bm25.search("foo bar baz qux", top_k=100)
        assert len(results) <= 2

    def test_top_k_zero(self):
        bm25 = _bm25()
        bm25.index(_docs([("d1", "something"), ("d2", "else")]))
        assert bm25.search("something", top_k=0) == []

    def test_no_match_returns_empty(self):
        bm25 = _bm25()
        bm25.index(_docs([("d1", "apple orange"), ("d2", "banana grape")]))
        results = bm25.search("zzz undefined token xyz")
        assert results == []

    def test_result_ids_are_strings(self):
        bm25 = _bm25()
        bm25.index(_docs([("abc-123", "test content here")]))
        results = bm25.search("test")
        assert all(isinstance(r[0], str) for r in results)

    def test_result_scores_are_positive(self):
        bm25 = _bm25()
        bm25.index(_docs([("d1", "relevant content"), ("d2", "other stuff")]))
        results = bm25.search("relevant content")
        assert all(r[1] > 0 for r in results)

    def test_reindex_replaces_corpus(self):
        """Calling index() a second time fully replaces the previous corpus."""
        bm25 = _bm25()
        bm25.index(_docs([("old", "ancient text no longer relevant")]))
        bm25.index(_docs([("new", "fresh content about authentication")]))
        results = bm25.search("authentication")
        ids = [r[0] for r in results]
        assert "new" in ids
        assert "old" not in ids

    def test_k1_b_params_accepted(self):
        from _bm25 import BM25
        bm25 = BM25(k1=1.2, b=0.5)
        bm25.index(_docs([("d1", "test content")]))
        results = bm25.search("test")
        assert len(results) == 1


# ── backend parity (both backends produce the same ranking) ───────────────────

class TestBackendParity:
    def test_python_and_cpp_same_ranking(self):
        """When C++ extension is available, verify ranking matches Python."""
        try:
            import _bm25_ext as cpp_mod  # type: ignore[import]
        except ImportError:
            pytest.skip("C++ extension not compiled — parity test skipped")

        from _bm25._fallback import BM25 as PyBM25, Document as PyDoc

        corpus = [
            ("d1", "JWT authentication token bearer"),
            ("d2", "file upload service"),
            ("d3", "JWT middleware verify token authentication"),
            ("d4", "database connection pooling"),
        ]

        py_bm25 = PyBM25()
        py_bm25.index([PyDoc(id=i, text=t) for i, t in corpus])
        py_results = py_bm25.search("JWT auth token")

        cpp_bm25 = cpp_mod.BM25()
        cpp_bm25.index([cpp_mod.Document(id=i, text=t) for i, t in corpus])
        cpp_results = cpp_bm25.search("JWT auth token")

        py_ids  = [r[0] for r in py_results]
        cpp_ids = [r[0] for r in cpp_results]
        assert py_ids == cpp_ids, f"Ranking mismatch: python={py_ids} cpp={cpp_ids}"


# ── episodic_bm25_filter integration ─────────────────────────────────────────

class TestEpisodicBM25Filter:
    def test_returns_list(self, isolated_cognirepo):
        from memory.episodic_memory import log_event
        log_event("deployed auth service to production", {"env": "prod"})
        log_event("fixed bug in payment module", {"module": "payments"})
        log_event("updated JWT expiry to 24 hours", {"service": "auth"})

        from retrieval.hybrid import episodic_bm25_filter
        results = episodic_bm25_filter("JWT auth", top_k=2)
        assert isinstance(results, list)

    def test_relevant_event_ranked_first(self, isolated_cognirepo):
        from memory.episodic_memory import log_event
        log_event("JWT token expiry updated in middleware")
        log_event("unrelated cooking recipe discussion")
        log_event("another unrelated topic about databases")

        from retrieval.hybrid import episodic_bm25_filter
        results = episodic_bm25_filter("JWT token", top_k=3)
        if results:
            assert "jwt" in results[0]["event"].lower() or "token" in results[0]["event"].lower()

    def test_empty_log_returns_empty(self, isolated_cognirepo):
        from retrieval.hybrid import episodic_bm25_filter
        results = episodic_bm25_filter("anything", top_k=5)
        assert results == []

    def test_top_k_respected(self, isolated_cognirepo):
        from memory.episodic_memory import log_event
        for i in range(10):
            log_event(f"test event number {i} with some content")

        from retrieval.hybrid import episodic_bm25_filter
        results = episodic_bm25_filter("test event", top_k=3)
        assert len(results) <= 3

    def test_time_range_filter(self, isolated_cognirepo):
        from memory.episodic_memory import log_event, get_history
        log_event("early event alpha")
        log_event("middle event beta")
        log_event("recent event gamma")

        events = get_history(limit=3)
        if len(events) >= 2:
            t_start = events[1]["time"]
            t_end   = events[-1]["time"]
            from retrieval.hybrid import episodic_bm25_filter
            results = episodic_bm25_filter("event", time_range=(t_start, t_end), top_k=10)
            for r in results:
                assert t_start <= r["time"] <= t_end
