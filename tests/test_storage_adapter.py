# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tests/test_storage_adapter.py — Sprint 4 acceptance tests for TASK-012.

Covers:
  - VectorStorageAdapter ABC is not directly instantiable
  - FAISSAdapter implements the full interface (add / search / search_with_scores / remove / persist)
  - ChromaDBAdapter raises ImportError when chromadb is not available
  - get_storage_adapter() factory returns FAISSAdapter by default
  - get_storage_adapter() returns ChromaDBAdapter when config says "chroma"
"""
from __future__ import annotations

import json
from pathlib import Path
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
        assert abstract_methods == {"add", "search", "search_with_scores", "remove", "persist"}


# ── FAISSAdapter ──────────────────────────────────────────────────────────────

class TestFAISSAdapter:
    def _make_adapter(self, tmp_path, monkeypatch):
        """Return a FAISSAdapter wired to a temp directory."""
        monkeypatch.setenv("COGNIREPO_ROOT", str(tmp_path))
        # Patch path helpers so FAISS files land in tmp_path
        monkeypatch.setattr(
            "vector_db.local_vector_db._index_file",
            lambda: str(tmp_path / "semantic.index"),
        )
        monkeypatch.setattr(
            "vector_db.local_vector_db._meta_file",
            lambda: str(tmp_path / "semantic_metadata.json"),
        )
        # Disable encryption
        monkeypatch.setattr("vector_db.local_vector_db.LocalVectorDB._load_meta", lambda self: [])
        from vector_db.faiss_adapter import FAISSAdapter
        return FAISSAdapter(dim=4)

    def test_implements_adapter_interface(self):
        from vector_db.adapter import VectorStorageAdapter
        from vector_db.faiss_adapter import FAISSAdapter
        assert issubclass(FAISSAdapter, VectorStorageAdapter)

    def test_add_and_search(self, tmp_path, monkeypatch):
        adapter = self._make_adapter(tmp_path, monkeypatch)
        monkeypatch.setattr(adapter._db, "save", MagicMock())

        vec = np.array([0.1, 0.2, 0.3, 0.4], dtype="float32")
        adapter.add(vec, "hello world", importance=0.9, source="memory")

        results = adapter.search(vec, top_k=1)
        assert len(results) == 1
        assert results[0]["text"] == "hello world"

    def test_search_with_scores_returns_distance(self, tmp_path, monkeypatch):
        adapter = self._make_adapter(tmp_path, monkeypatch)
        monkeypatch.setattr(adapter._db, "save", MagicMock())

        vec = np.array([0.1, 0.2, 0.3, 0.4], dtype="float32")
        adapter.add(vec, "test entry", importance=0.5, source="memory")

        results = adapter.search_with_scores(vec, top_k=1)
        assert len(results) == 1
        assert "l2_distance" in results[0]
        assert "faiss_row" in results[0]

    def test_remove_is_no_op_without_crash(self, tmp_path, monkeypatch):
        """FAISSAdapter.remove() logs a warning but must not raise."""
        adapter = self._make_adapter(tmp_path, monkeypatch)
        adapter.remove([0, 1, 2])  # should not raise

    def test_persist_calls_save(self, tmp_path, monkeypatch):
        adapter = self._make_adapter(tmp_path, monkeypatch)
        adapter._db.save = MagicMock()
        adapter.persist()
        adapter._db.save.assert_called_once()

    def test_source_filter(self, tmp_path, monkeypatch):
        adapter = self._make_adapter(tmp_path, monkeypatch)
        monkeypatch.setattr(adapter._db, "save", MagicMock())

        vec = np.array([0.1, 0.2, 0.3, 0.4], dtype="float32")
        adapter.add(vec, "memory entry", importance=0.5, source="memory")
        adapter.add(vec, "symbol entry", importance=0.5, source="symbol")

        memory_results = adapter.search(vec, top_k=5, source="memory")
        symbol_results = adapter.search(vec, top_k=5, source="symbol")

        assert all(r["source"] == "memory" for r in memory_results)
        assert all(r["source"] == "symbol" for r in symbol_results)


# ── ChromaDBAdapter ───────────────────────────────────────────────────────────

class TestChromaDBAdapter:
    def test_raises_import_error_when_chromadb_missing(self, monkeypatch):
        """When chromadb is not installed, instantiating the adapter must raise."""
        import sys
        with patch.dict(sys.modules, {"chromadb": None}):
            import importlib
            import vector_db.chroma_adapter as mod
            importlib.reload(mod)
            with pytest.raises(ImportError, match="chromadb is not installed"):
                mod.ChromaDBAdapter()
            # Restore
            importlib.reload(mod)

    def test_implements_adapter_interface(self):
        from vector_db.adapter import VectorStorageAdapter
        from vector_db.chroma_adapter import ChromaDBAdapter
        assert issubclass(ChromaDBAdapter, VectorStorageAdapter)


# ── get_storage_adapter() factory ─────────────────────────────────────────────

class TestGetStorageAdapter:
    def test_default_returns_faiss(self, tmp_path, monkeypatch):
        """When config.json is absent (or has no vector_backend), return FAISSAdapter."""
        from vector_db.faiss_adapter import FAISSAdapter
        # Patch get_path inside vector_db module to point at a non-existent config
        monkeypatch.setattr(
            "config.paths.get_path",
            lambda key: str(tmp_path / "no_config.json"),
        )
        import importlib
        import vector_db
        importlib.reload(vector_db)  # pick up the monkeypatched get_path

        adapter = vector_db.get_storage_adapter()
        assert isinstance(adapter, FAISSAdapter)

    def test_chroma_config_returns_chroma_adapter_class(self, tmp_path, monkeypatch):
        """When config says 'chroma', the factory tries to return ChromaDBAdapter."""
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"vector_backend": "chroma"}))

        monkeypatch.setattr(
            "config.paths.get_path",
            lambda key: str(config),
        )

        # ChromaDB may not be installed — just verify the right path is taken
        from vector_db.chroma_adapter import ChromaDBAdapter, _CHROMA_AVAILABLE
        if not _CHROMA_AVAILABLE:
            with pytest.raises(ImportError, match="chromadb is not installed"):
                import vector_db
                vector_db.get_storage_adapter()
        else:
            import vector_db
            adapter = vector_db.get_storage_adapter()
            assert isinstance(adapter, ChromaDBAdapter)
