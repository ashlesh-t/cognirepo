# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_storage_adapter.py — Sprint 4 acceptance tests for TASK-012.

Covers:
  - VectorStorageAdapter ABC is not directly instantiable
  - LocalVectorDB implements the full interface (add / search / search_with_scores / remove / persist)
  - ChromaDBAdapter raises ImportError when chromadb is not available
  - get_vector_adapter() factory returns LocalVectorDB by default
  - get_vector_adapter() returns ChromaDBAdapter when config says "chroma"
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ── VectorStorageAdapter ABC ──────────────────────────────────────────────────

class TestAdapterABC:
    def test_cannot_instantiate_abc(self):
        from vector_db.adapter import VectorStorageAdapter
        with pytest.raises(TypeError):
            VectorStorageAdapter()  # type: ignore[abstract]

    def test_all_abstract_methods_declared(self):
        from vector_db.adapter import VectorStorageAdapter
        import inspect
        abstract_methods = {
            name for name, method in inspect.getmembers(VectorStorageAdapter)
            if getattr(method, "__isabstractmethod__", False)
        }
        assert abstract_methods == {
            "add", "search", "search_with_scores", "remove", "persist",
            "update_behaviour_score", "count",
        }


# ── LocalVectorDB (replaces deleted FAISSAdapter) ────────────────────────────

class TestLocalVectorDB:
    def _make_adapter(self, tmp_path, monkeypatch):
        """Return a LocalVectorDB wired to a temp directory."""
        monkeypatch.setattr(
            "vector_db.local_vector_db._index_file",
            lambda: str(tmp_path / "semantic.index"),
        )
        monkeypatch.setattr(
            "vector_db.local_vector_db._meta_file",
            lambda: str(tmp_path / "semantic_metadata.json"),
        )
        monkeypatch.setattr("vector_db.local_vector_db.LocalVectorDB._load_meta", lambda self: [])
        from vector_db.local_vector_db import LocalVectorDB
        return LocalVectorDB(dim=4)

    def test_implements_adapter_interface(self):
        from vector_db.adapter import VectorStorageAdapter
        from vector_db.local_vector_db import LocalVectorDB
        assert issubclass(LocalVectorDB, VectorStorageAdapter)

    def test_add_and_search(self, tmp_path, monkeypatch):
        adapter = self._make_adapter(tmp_path, monkeypatch)
        monkeypatch.setattr(adapter, "save", MagicMock())

        vec = np.array([0.1, 0.2, 0.3, 0.4], dtype="float32")
        adapter.add(vec, "hello world", importance=0.9, source="memory")

        results = adapter.search(vec, top_k=1)
        assert len(results) == 1
        assert results[0]["text"] == "hello world"

    def test_search_with_scores_returns_distance(self, tmp_path, monkeypatch):
        adapter = self._make_adapter(tmp_path, monkeypatch)
        monkeypatch.setattr(adapter, "save", MagicMock())

        vec = np.array([0.1, 0.2, 0.3, 0.4], dtype="float32")
        adapter.add(vec, "test entry", importance=0.5, source="memory")

        results = adapter.search_with_scores(vec, top_k=1)
        assert len(results) == 1
        assert "l2_distance" in results[0]
        assert "faiss_row" in results[0]
        assert "combined_score" in results[0]

    def test_remove_is_soft_delete(self, tmp_path, monkeypatch):
        """LocalVectorDB.remove() soft-deletes via deprecate_row — must not raise."""
        adapter = self._make_adapter(tmp_path, monkeypatch)
        monkeypatch.setattr(adapter, "save", MagicMock())
        vec = np.array([0.1, 0.2, 0.3, 0.4], dtype="float32")
        adapter.add(vec, "to remove", importance=0.5)
        adapter.remove([0])  # should not raise

    def test_persist_calls_save(self, tmp_path, monkeypatch):
        adapter = self._make_adapter(tmp_path, monkeypatch)
        adapter.save = MagicMock()
        adapter.persist()
        adapter.save.assert_called_once()

    def test_source_filter(self, tmp_path, monkeypatch):
        adapter = self._make_adapter(tmp_path, monkeypatch)
        monkeypatch.setattr(adapter, "save", MagicMock())

        vec = np.array([0.1, 0.2, 0.3, 0.4], dtype="float32")
        adapter.add(vec, "memory entry", importance=0.5, source="memory")
        adapter.add(vec, "symbol entry", importance=0.5, source="symbol")

        memory_results = adapter.search(vec, top_k=5, source="memory")
        symbol_results = adapter.search(vec, top_k=5, source="symbol")

        assert all(r["source"] == "memory" for r in memory_results)
        assert all(r["source"] == "symbol" for r in symbol_results)

    def test_update_behaviour_score(self, tmp_path, monkeypatch):
        adapter = self._make_adapter(tmp_path, monkeypatch)
        monkeypatch.setattr(adapter, "_save_meta", MagicMock())

        vec = np.array([0.1, 0.2, 0.3, 0.4], dtype="float32")
        monkeypatch.setattr(adapter, "save", MagicMock())
        adapter.add(vec, "scored entry", importance=0.5, behaviour_score=0.0)
        adapter.update_behaviour_score(0, new_score=0.5)
        assert adapter.metadata[0]["behaviour_score"] == 0.5


# ── ChromaDBAdapter ───────────────────────────────────────────────────────────

class TestChromaDBAdapter:
    def test_raises_import_error_when_chromadb_missing(self, monkeypatch):  # pylint: disable=unused-argument
        """When chromadb is not installed, instantiating the adapter must raise."""
        import sys
        with patch.dict(sys.modules, {"chromadb": None}):
            import importlib
            import vector_db.chroma_adapter as mod
            importlib.reload(mod)
            with pytest.raises(ImportError, match="chromadb is not installed"):
                mod.ChromaDBAdapter()
            importlib.reload(mod)

    def test_implements_adapter_interface(self):
        from vector_db.adapter import VectorStorageAdapter
        from vector_db.chroma_adapter import ChromaDBAdapter
        assert issubclass(ChromaDBAdapter, VectorStorageAdapter)


# ── get_vector_adapter() factory ──────────────────────────────────────────────

class TestGetVectorAdapter:
    def test_default_returns_local_vector_db(self, tmp_path, monkeypatch):
        """When config.json is absent (or has no vector_backend), return LocalVectorDB."""
        from vector_db.local_vector_db import LocalVectorDB
        monkeypatch.setattr(
            "vector_db.factory._find_config",
            lambda: None,
        )
        from vector_db.factory import get_vector_adapter
        monkeypatch.setattr(
            "vector_db.local_vector_db._index_file",
            lambda: str(tmp_path / "semantic.index"),
        )
        monkeypatch.setattr(
            "vector_db.local_vector_db._meta_file",
            lambda: str(tmp_path / "semantic_metadata.json"),
        )
        monkeypatch.setattr("vector_db.local_vector_db.LocalVectorDB._load_meta", lambda self: [])
        adapter = get_vector_adapter()
        assert isinstance(adapter, LocalVectorDB)

    def test_chroma_config_returns_chroma_adapter_class(self, tmp_path, monkeypatch):
        """When config says 'chroma', the factory tries to return ChromaDBAdapter."""
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"storage": {"vector_backend": "chroma"}}))

        monkeypatch.setattr(
            "vector_db.factory._find_config",
            lambda: config,
        )

        from vector_db.chroma_adapter import ChromaDBAdapter, _CHROMA_AVAILABLE
        from vector_db.factory import get_vector_adapter
        if not _CHROMA_AVAILABLE:
            # Falls back to LocalVectorDB when chromadb not installed
            monkeypatch.setattr(
                "vector_db.local_vector_db._index_file",
                lambda: str(tmp_path / "semantic.index"),
            )
            monkeypatch.setattr(
                "vector_db.local_vector_db._meta_file",
                lambda: str(tmp_path / "semantic_metadata.json"),
            )
            monkeypatch.setattr("vector_db.local_vector_db.LocalVectorDB._load_meta", lambda self: [])
            from vector_db.local_vector_db import LocalVectorDB
            adapter = get_vector_adapter()
            assert isinstance(adapter, LocalVectorDB)
        else:
            adapter = get_vector_adapter()
            assert isinstance(adapter, ChromaDBAdapter)
