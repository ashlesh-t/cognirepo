# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
vector_db/chroma_adapter.py — Optional VectorStorageAdapter backed by ChromaDB.

Requires: pip install chromadb
Enabled via config.json: {"vector_backend": "chroma"}

If chromadb is not installed, importing this module still works — ChromaDBAdapter
will raise ImportError only when instantiated, so the import-time check in
get_storage_adapter() can give a clear error message.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from vector_db.adapter import VectorStorageAdapter

log = logging.getLogger(__name__)

try:
    import chromadb  # type: ignore[import]
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False


class ChromaDBAdapter(VectorStorageAdapter):
    """
    VectorStorageAdapter backed by ChromaDB persistent client.

    Parameters
    ----------
    collection_name : ChromaDB collection to use (default "cognirepo")
    path            : Directory for ChromaDB persistent storage.
                      Defaults to .cognirepo/vector_db/chroma
    """

    def __init__(
        self,
        collection_name: str = "cognirepo",
        path: Optional[str] = None,
    ) -> None:
        if not _CHROMA_AVAILABLE:
            raise ImportError(
                "chromadb is not installed. "
                "Run: pip install chromadb  (or pip install 'cognirepo[chroma]')"
            )
        if path is None:
            from config.paths import get_path  # pylint: disable=import-outside-toplevel
            path = get_path("vector_db/chroma")

        self._client = chromadb.PersistentClient(path=path)
        self._col = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "l2"},
        )
        self._next_id = self._col.count()

    # ── VectorStorageAdapter interface ────────────────────────────────────────

    def add(
        self,
        vector: np.ndarray,
        text: str,
        importance: float,
        source: str = "memory",
    ) -> None:
        doc_id = str(self._next_id)
        self._next_id += 1
        self._col.add(
            ids=[doc_id],
            embeddings=[vector.tolist()],
            documents=[text],
            metadatas=[{"importance": importance, "source": source, "text": text}],
        )

    def search(
        self,
        vector: np.ndarray,
        top_k: int = 5,
        source: Optional[str] = None,
    ) -> list[dict]:
        where = {"source": source} if source else None
        n = min(top_k, self._col.count())
        if n == 0:
            return []
        kwargs: dict = {"query_embeddings": [vector.tolist()], "n_results": n}
        if where:
            kwargs["where"] = where
        res = self._col.query(**kwargs)
        results = []
        for meta in (res.get("metadatas") or [[]])[0]:
            results.append({
                "text": meta.get("text", ""),
                "importance": meta.get("importance", 0.5),
                "source": meta.get("source", "memory"),
            })
        return results

    def search_with_scores(
        self,
        vector: np.ndarray,
        top_k: int = 5,
        source: Optional[str] = None,
    ) -> list[dict]:
        where = {"source": source} if source else None
        n = min(top_k, self._col.count())
        if n == 0:
            return []
        kwargs: dict = {
            "query_embeddings": [vector.tolist()],
            "n_results": n,
            "include": ["metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where
        res = self._col.query(**kwargs)
        results = []
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        for i, meta in enumerate(metas):
            entry = {
                "text": meta.get("text", ""),
                "importance": meta.get("importance", 0.5),
                "source": meta.get("source", "memory"),
                "l2_distance": float(dists[i]) if i < len(dists) else 0.0,
                "faiss_row": i,
            }
            results.append(entry)
        return results

    def remove(self, ids: list[int]) -> None:
        """Remove entries by integer ID (converted to string IDs used on insert)."""
        str_ids = [str(i) for i in ids]
        try:
            self._col.delete(ids=str_ids)
        except Exception as exc:  # pylint: disable=broad-except
            log.warning("ChromaDBAdapter.remove() failed: %s", exc)

    def persist(self) -> None:
        # ChromaDB PersistentClient auto-persists; this is a no-op.
        pass
