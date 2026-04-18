# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_cache.py — unit tests for LRU cache on lookup_symbol
and TTL cache on hybrid_retrieve.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestLookupSymbolCache:
    """Tests for @lru_cache on ASTIndexer.lookup_symbol."""

    def _make_indexer(self, reverse_index: dict) -> "ASTIndexer":
        from graph.knowledge_graph import KnowledgeGraph
        from indexer.ast_indexer import ASTIndexer
        # clear any stale cache state before each test
        ASTIndexer.lookup_symbol.cache_clear()
        kg = MagicMock(spec=KnowledgeGraph)
        kg.G = MagicMock()
        with patch("indexer.ast_indexer.get_model", return_value=MagicMock()):
            indexer = ASTIndexer(graph=kg)
        indexer.index_data["reverse_index"] = reverse_index
        return indexer

    def test_lookup_returns_correct_locations(self):
        from indexer.ast_indexer import ASTIndexer
        rev = {"my_function": [["src/foo.py", 10], ["src/bar.py", 20]]}
        indexer = self._make_indexer(rev)
        result = indexer.lookup_symbol("my_function")
        assert result == [{"file": "src/foo.py", "line": 10}, {"file": "src/bar.py", "line": 20}]

    def test_lookup_missing_symbol_returns_empty(self):
        indexer = self._make_indexer({})
        result = indexer.lookup_symbol("nonexistent")
        assert result == []

    def test_repeated_calls_use_cache(self):
        """Second call to lookup_symbol with same arg should hit the lru_cache."""
        from indexer.ast_indexer import ASTIndexer
        rev = {"cached_fn": [["a.py", 5]]}
        indexer = self._make_indexer(rev)
        ASTIndexer.lookup_symbol.cache_clear()

        result1 = indexer.lookup_symbol("cached_fn")
        info_after_first = ASTIndexer.lookup_symbol.cache_info()
        assert info_after_first.misses == 1
        assert info_after_first.hits == 0

        result2 = indexer.lookup_symbol("cached_fn")
        info_after_second = ASTIndexer.lookup_symbol.cache_info()
        assert info_after_second.hits == 1
        assert result1 == result2

    def test_cache_cleared_after_build_reverse_index(self):
        """_build_reverse_index must call cache_clear() so fresh results are served."""
        from indexer.ast_indexer import ASTIndexer
        rev = {"fn_old": [["old.py", 1]]}
        indexer = self._make_indexer(rev)
        ASTIndexer.lookup_symbol.cache_clear()

        # prime the cache
        indexer.lookup_symbol("fn_old")
        info = ASTIndexer.lookup_symbol.cache_info()
        assert info.misses == 1

        # rebuild reverse index (simulating a new file being added)
        indexer.index_data["files"]["new.py"] = {
            "symbols": [{"name": "fn_new", "start_line": 5}]
        }
        indexer._build_reverse_index()

        # cache should have been cleared
        info_after = ASTIndexer.lookup_symbol.cache_info()
        assert info_after.currsize == 0

        # fresh lookup for new symbol should work
        result = indexer.lookup_symbol("fn_new")
        assert result == [{"file": "new.py", "line": 5}]


class TestHybridRetrieveCache:
    """Tests for TTL cache on hybrid_retrieve."""

    def setup_method(self):
        from retrieval.hybrid import invalidate_hybrid_cache
        invalidate_hybrid_cache()  # reset between tests

    def test_cache_miss_then_hit(self):
        from retrieval import hybrid as h
        from retrieval.hybrid import invalidate_hybrid_cache
        invalidate_hybrid_cache()

        mock_result = [{"text": "result", "final_score": 0.9}]
        with patch.object(h, "HybridRetriever") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.retrieve.return_value = mock_result
            mock_cls.return_value = mock_instance

            result1 = h.hybrid_retrieve("test query", top_k=3)
            result2 = h.hybrid_retrieve("test query", top_k=3)

        # HybridRetriever should only be instantiated once (second call is cached)
        assert mock_cls.call_count == 1
        assert result1 == result2 == mock_result

    def test_different_queries_not_shared(self):
        from retrieval import hybrid as h
        from retrieval.hybrid import invalidate_hybrid_cache
        invalidate_hybrid_cache()

        with patch.object(h, "HybridRetriever") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.retrieve.side_effect = lambda q, top_k: [{"text": q}]
            mock_cls.return_value = mock_instance

            r1 = h.hybrid_retrieve("query_a", top_k=5)
            r2 = h.hybrid_retrieve("query_b", top_k=5)

        assert r1 != r2
        assert mock_cls.call_count == 2

    def test_invalidate_clears_cache(self):
        from retrieval import hybrid as h
        from retrieval.hybrid import invalidate_hybrid_cache
        invalidate_hybrid_cache()

        mock_result = [{"text": "result", "final_score": 0.8}]
        with patch.object(h, "HybridRetriever") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.retrieve.return_value = mock_result
            mock_cls.return_value = mock_instance

            h.hybrid_retrieve("query", top_k=5)
            invalidate_hybrid_cache()
            h.hybrid_retrieve("query", top_k=5)

        # should have been called twice (cache was cleared between calls)
        assert mock_cls.call_count == 2

    def test_cache_expires_after_ttl(self):
        from retrieval import hybrid as h
        from retrieval.hybrid import invalidate_hybrid_cache
        invalidate_hybrid_cache()

        mock_result = [{"text": "result"}]
        with patch.object(h, "HybridRetriever") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.retrieve.return_value = mock_result
            mock_cls.return_value = mock_instance

            with patch("retrieval.hybrid.time") as mock_time:
                mock_time.monotonic.return_value = 0.0
                h.hybrid_retrieve("ttl_query", top_k=5)

                # advance time beyond TTL
                mock_time.monotonic.return_value = 400.0
                h.hybrid_retrieve("ttl_query", top_k=5)

        # both calls should hit HybridRetriever (first miss + expired)
        assert mock_cls.call_count == 2

    def test_cache_stats_available(self):
        from retrieval.hybrid import cache_stats
        stats = cache_stats()
        assert "hits" in stats
        assert "misses" in stats
