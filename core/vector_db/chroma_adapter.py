# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

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
import os
import time
from typing import Optional

import numpy as np

from core.config.atomic import atomic_write
from core.config.lock import store_lock
from core.vector_db.adapter import VectorStorageAdapter

log = logging.getLogger(__name__)

try:
    import chromadb  # type: ignore[import]
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False


def chroma_lock_path(store_path: str) -> str:
    """Lock file shared by every process using the chroma store at ``store_path``.

    A sibling of the store directory (``vector_db/chroma.lock``), so it survives the store being
    quarantined/renamed and is the same file for the factory and the adapter (COGNIREPO-142).
    """
    return os.path.join(os.path.dirname(os.path.abspath(store_path)), "chroma.lock")


_COUNTER_FILE = ".next_id"
_LOCK_TIMEOUT = 60.0


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
            from core.config.paths import get_path  # pylint: disable=import-outside-toplevel
            path = get_path("vector_db/chroma")

        self._path = path
        self._lock_path = chroma_lock_path(path)
        self._counter_path = os.path.join(path, _COUNTER_FILE)
        self._client, self._col = self._open_store(path, collection_name)
        #: id the NEXT add would use *in this process's view* — after an add it is last_id + 1, so
        #: callers (mcp_server) can read ``str(db._next_id - 1)`` as the id they just stored.
        self._next_id = self._col.count()

    # ── opening (COGNIREPO-142) ───────────────────────────────────────────────

    def _attempt_open(self, path: str, name: str):
        client = chromadb.PersistentClient(path=path)
        col = client.get_or_create_collection(name=name, metadata={"hnsw:space": "l2"})
        return client, col

    def _open_store(self, path: str, name: str):
        """Open (creating if needed) the store, safe against concurrent first-time creation.

        Two processes creating a fresh store at once race inside chroma's schema migration and
        one dies with ``InternalError: table collections already exists`` (observed: 1 of 6
        concurrent workers). Creation is serialized behind the store lock; opening an existing
        store takes no lock.
        """
        os.makedirs(path, exist_ok=True)
        db_exists = os.path.exists(os.path.join(path, "chroma.sqlite3"))
        if db_exists:
            try:
                return self._attempt_open(path, name)
            except Exception as exc:  # pylint: disable=broad-except
                if "already exists" not in str(exc):
                    raise
                # lost a creation race for the collection itself — retry under the lock below
        with store_lock(timeout=_LOCK_TIMEOUT, lock_path=self._lock_path):
            return self._attempt_open(path, name)

    # ── collision-free ids (COGNIREPO-142) ────────────────────────────────────

    def _scan_next_id(self) -> int:
        """One past the highest numeric id in the collection (0 if empty)."""
        try:
            ids = self._col.get(include=[])["ids"]
        except Exception:  # pylint: disable=broad-except
            return 0
        numeric = [int(i) for i in ids if str(i).isdigit()]
        return (max(numeric) + 1) if numeric else 0

    def _read_counter(self) -> "int | None":
        try:
            with open(self._counter_path, encoding="utf-8") as fh:
                return int(fh.read().strip())
        except (OSError, ValueError):
            return None

    def _alloc_ids(self, k: int) -> list[str]:
        """Reserve ``k`` ids no other process can hand out.

        The old scheme was ``id = col.count()`` read once at open. Two processes opening at the
        same count minted the same ids and chroma silently ignores an ``add`` of an existing id —
        the second writer's vectors vanished without an error (measured: 6 workers x 15 adds kept
        20 of 90). It also collided after any ``remove()`` (count < highest id). Ids stay numeric
        strings (callers use them as row ids); they come from a counter file advanced under the
        store lock *before* the add, so a crash can leave gaps but never a duplicate. The start is
        never below the live ``count()``, which also protects against an older writer that still
        uses count-based ids.
        """
        with store_lock(timeout=_LOCK_TIMEOUT, lock_path=self._lock_path):
            counter = self._read_counter()
            if counter is None:
                counter = self._scan_next_id()
            try:
                live = self._col.count()
            except Exception:  # pylint: disable=broad-except
                live = 0
            start = max(counter, live)
            atomic_write(self._counter_path, str(start + k), fsync=False)
        self._next_id = start + k
        return [str(start + i) for i in range(k)]

    # ── VectorStorageAdapter interface ────────────────────────────────────────

    def add(
        self,
        vector: np.ndarray,
        text: str,
        importance: float,
        source: str = "memory",
        behaviour_score: float = 0.0,
    ) -> None:
        (doc_id,) = self._alloc_ids(1)
        self._col.add(
            ids=[doc_id],
            embeddings=[vector.tolist()],
            documents=[text],
            metadatas=[{
                "importance": importance,
                "source": source,
                "text": text,
                "behaviour_score": behaviour_score,
            }],
        )

    def add_batch(
        self,
        entries: list[tuple],
        source: str = "memory",
    ) -> int:
        """
        Add multiple vectors in one Chroma upsert and return count stored.
        Each entry is (vector, text, importance) or (vector, text, importance, source).
        """
        if not entries:
            return 0
        ids = self._alloc_ids(len(entries))
        embeddings, documents, metadatas = [], [], []
        for item in entries:
            vec, text, importance = item[0], item[1], item[2]
            entry_source = item[3] if len(item) > 3 else source
            embeddings.append(vec.tolist())
            documents.append(text)
            metadatas.append({
                "importance": importance,
                "source": entry_source,
                "text": text,
                "behaviour_score": 0.0,
            })
        self._col.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
        return len(entries)

    def update_behaviour_score(self, row_id: int, new_score: float) -> bool:
        """Update behaviour_score metadata for a Chroma entry (row_id = insert order)."""
        doc_id = str(row_id)
        try:
            self._col.update(ids=[doc_id], metadatas=[{"behaviour_score": float(new_score)}])
            return True
        except Exception as exc:  # pylint: disable=broad-except
            log.warning("ChromaDBAdapter.update_behaviour_score() failed: %s", exc)
            return False

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
        # "ids" is always returned by ChromaDB query() and must NOT appear in include.
        kwargs["include"] = ["metadatas"]
        res = self._col.query(**kwargs)
        results = []
        ids_list = (res.get("ids") or [[]])[0]   # always present regardless of include
        for i, meta in enumerate((res.get("metadatas") or [[]])[0]):
            results.append({
                "id": ids_list[i] if i < len(ids_list) else "",
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
            dist = float(dists[i]) if i < len(dists) else 0.0
            l2_score = max(0.0, 1.0 - dist / 2.0)
            b_score = float(meta.get("behaviour_score", 0.0))
            entry = {
                "text": meta.get("text", ""),
                "importance": meta.get("importance", 0.5),
                "source": meta.get("source", "memory"),
                "behaviour_score": b_score,
                "l2_distance": dist,
                "faiss_row": i,
                "combined_score": round(l2_score * 0.8 + b_score * 0.2, 4),
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

    def count(self) -> int:
        """Return total number of vectors in the collection."""
        try:
            return self._col.count()
        except Exception:
            return 0

    def persist(self) -> None:
        # ChromaDB PersistentClient auto-persists; this is a no-op.
        pass
