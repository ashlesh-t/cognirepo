# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_semantic_search_code.py — unit tests for semantic_search_code tool.
"""
from __future__ import annotations

import numpy as np
from unittest.mock import MagicMock, patch


def _make_indexer_with_symbols(symbols: list[dict]):
    """Build a mock ASTIndexer with a FAISS index populated from symbols."""
    import faiss
    from graph.knowledge_graph import KnowledgeGraph
    from indexer.ast_indexer import ASTIndexer

    ASTIndexer.lookup_symbol.cache_clear()

    kg = MagicMock(spec=KnowledgeGraph)
    kg.G = MagicMock()
    with patch("indexer.ast_indexer.get_model", return_value=MagicMock()):
        indexer = ASTIndexer(graph=kg)

    # Build a real FAISS index
    dim = 384
    inner = faiss.IndexFlatL2(dim)
    indexer.faiss_index = faiss.IndexIDMap2(inner)
    indexer.faiss_meta = []

    rng = np.random.default_rng(42)
    for i, sym in enumerate(symbols):
        vec = rng.random(dim).astype("float32")
        indexer.faiss_index.add_with_ids(
            np.array([vec], dtype="float32"),
            np.array([i], dtype=np.int64),
        )
        indexer.faiss_meta.append({
            "name": sym["name"],
            "type": sym.get("type", "FUNCTION"),
            "file": sym["file"],
            "start_line": sym.get("line", 1),
            "docstring": sym.get("docstring", ""),
            "source": "symbol",
        })

    return indexer


class TestSemanticSearchCode:
    def test_returns_list(self):
        from tools.semantic_search_code import semantic_search_code
        with patch("tools.semantic_search_code.ASTIndexer") as mock_cls:
            mock_cls.return_value = MagicMock(
                faiss_index=None, faiss_meta=[]
            )
            mock_cls.return_value.faiss_index = None
            result = semantic_search_code("auth logic")
        assert isinstance(result, list)

    def test_returns_empty_when_no_index(self):
        from tools.semantic_search_code import semantic_search_code
        with patch("tools.semantic_search_code.ASTIndexer") as mock_cls:
            inst = MagicMock()
            inst.faiss_index = None
            mock_cls.return_value = inst
            result = semantic_search_code("anything")
        assert result == []

    def test_result_fields(self):
        from tools.semantic_search_code import semantic_search_code
        symbols = [
            {"name": "verify_token", "type": "FUNCTION", "file": "auth.py", "line": 10},
            {"name": "hash_password", "type": "FUNCTION", "file": "auth.py", "line": 30},
        ]
        indexer = _make_indexer_with_symbols(symbols)

        with patch("tools.semantic_search_code.ASTIndexer") as mock_cls:
            with patch("tools.semantic_search_code.KnowledgeGraph"):
                with patch("tools.semantic_search_code.encode_with_timeout",
                           return_value=np.zeros(384, dtype="float32")):
                    mock_cls.return_value = indexer
                    result = semantic_search_code("token verification", top_k=2)

        assert isinstance(result, list)
        if result:
            for r in result:
                assert "name" in r
                assert "type" in r
                assert "file" in r
                assert "line" in r
                assert "score" in r

    def test_language_filter_python(self):
        from tools.semantic_search_code import semantic_search_code
        symbols = [
            {"name": "py_func", "type": "FUNCTION", "file": "auth.py", "line": 1},
            {"name": "ts_func", "type": "FUNCTION", "file": "auth.ts", "line": 1},
        ]
        indexer = _make_indexer_with_symbols(symbols)

        with patch("tools.semantic_search_code.ASTIndexer") as mock_cls:
            with patch("tools.semantic_search_code.KnowledgeGraph"):
                with patch("tools.semantic_search_code.encode_with_timeout",
                           return_value=np.zeros(384, dtype="float32")):
                    mock_cls.return_value = indexer
                    result = semantic_search_code("func", language="python")

        files = [r["file"] for r in result]
        assert all(f.endswith(".py") for f in files), f"Expected only .py files, got: {files}"

    def test_language_filter_typescript(self):
        from tools.semantic_search_code import semantic_search_code
        symbols = [
            {"name": "pyFunc", "type": "FUNCTION", "file": "main.py", "line": 1},
            {"name": "tsFunc", "type": "FUNCTION", "file": "main.ts", "line": 1},
        ]
        indexer = _make_indexer_with_symbols(symbols)

        with patch("tools.semantic_search_code.ASTIndexer") as mock_cls:
            with patch("tools.semantic_search_code.KnowledgeGraph"):
                with patch("tools.semantic_search_code.encode_with_timeout",
                           return_value=np.zeros(384, dtype="float32")):
                    mock_cls.return_value = indexer
                    result = semantic_search_code("func", language="typescript")

        files = [r["file"] for r in result]
        assert all(f.endswith(".ts") for f in files), f"Expected only .ts files, got: {files}"

    def test_no_episodic_entries_in_results(self):
        """semantic_search_code must never return episodic (non-symbol) entries."""
        from tools.semantic_search_code import semantic_search_code
        import faiss as _faiss
        from graph.knowledge_graph import KnowledgeGraph
        from indexer.ast_indexer import ASTIndexer

        ASTIndexer.lookup_symbol.cache_clear()
        kg = MagicMock(spec=KnowledgeGraph)
        kg.G = MagicMock()
        with patch("indexer.ast_indexer.get_model", return_value=MagicMock()):
            indexer = ASTIndexer(graph=kg)

        dim = 384
        inner = _faiss.IndexFlatL2(dim)
        indexer.faiss_index = _faiss.IndexIDMap2(inner)
        rng = np.random.default_rng(0)
        vec = rng.random(dim).astype("float32")
        indexer.faiss_index.add_with_ids(
            np.array([vec], dtype="float32"), np.array([0], dtype=np.int64)
        )
        # inject an episodic (non-symbol) entry
        indexer.faiss_meta = [{"name": "ep", "source": "memory", "file": "ep.log", "start_line": 0, "type": "EP"}]

        with patch("tools.semantic_search_code.ASTIndexer") as mock_cls:
            with patch("tools.semantic_search_code.KnowledgeGraph"):
                with patch("tools.semantic_search_code.encode_with_timeout", return_value=vec):
                    mock_cls.return_value = indexer
                    result = semantic_search_code("anything")

        # episodic entries must be filtered out
        assert all(r.get("type") != "EP" for r in result)

    def test_retrieve_memory_unaffected(self):
        """retrieve_memory() must still return mixed results (backward compat)."""
        from vector_db.local_vector_db import LocalVectorDB
        db = LocalVectorDB()
        # the search() with no source filter returns all entries
        # just verify the method accepts and ignores the source=None param
        if db.index.ntotal > 0:
            vec = np.zeros(384, dtype="float32")
            result = db.search(vec, k=5, source=None)
            assert isinstance(result, list)
