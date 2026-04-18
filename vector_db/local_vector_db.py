# pylint: disable=duplicate-code
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Local vector database module using FAISS for storing and searching semantic embeddings.
"""

import os
import json
from datetime import datetime, timezone
# pylint: disable=import-error
import faiss
import numpy as np

from config.paths import get_path
from config.lock import store_lock
from vector_db.adapter import VectorStorageAdapter


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()

def _index_file() -> str:
    return get_path("vector_db/semantic.index")

def _meta_file() -> str:
    return get_path("memory/semantic_metadata.json")


class LocalVectorDB(VectorStorageAdapter):
    """
    Local vector database using FAISS for storing and searching semantic embeddings.
    """

    def __init__(self, dim=384):
        """
        Initializes the LocalVectorDB with the specified dimensionality.
        """
        import logging  # pylint: disable=import-outside-toplevel
        self.dim = dim
        if os.path.exists(_index_file()):
            try:
                self.index = faiss.read_index(_index_file())
            except Exception as exc:  # pylint: disable=broad-except
                logging.getLogger(__name__).warning(
                    "semantic.index could not be loaded (%s). "
                    "This may be a platform mismatch (e.g. x86 index on ARM) or "
                    "a corrupted file. Starting with an empty index — re-run "
                    "`cognirepo index-repo .` to rebuild.",
                    exc,
                )
                stale = _index_file() + ".stale"
                try:
                    os.rename(_index_file(), stale)
                except OSError:
                    pass
                self.index = faiss.IndexFlatL2(dim)
        else:
            self.index = faiss.IndexFlatL2(dim)

        if os.path.exists(_meta_file()):
            self.metadata = self._load_meta()
        else:
            self.metadata = []

    # ── metadata persistence (with optional encryption) ───────────────────────

    def _load_meta(self) -> list:
        with open(_meta_file(), "rb") as f:
            raw = f.read()
        from security import get_storage_config  # pylint: disable=import-outside-toplevel
        encrypt, project_id = get_storage_config()
        if encrypt:
            from security.encryption import get_or_create_key, decrypt_bytes  # pylint: disable=import-outside-toplevel
            try:
                raw = decrypt_bytes(raw, get_or_create_key(project_id))
            except Exception:  # pylint: disable=broad-except
                # Key mismatch or corrupted file — start with a clean slate.
                # The stale file will be overwritten on the next save().
                import logging  # pylint: disable=import-outside-toplevel
                logging.getLogger(__name__).warning(
                    "semantic_metadata.json could not be decrypted (key mismatch or "
                    "corruption). Starting with empty metadata — existing entries will "
                    "be lost on next store_memory call."
                )
                return []
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            import logging  # pylint: disable=import-outside-toplevel
            logging.getLogger(__name__).warning(
                "semantic_metadata.json is not valid JSON. Starting with empty metadata."
            )
            return []

    def _save_meta(self) -> None:
        from security import get_storage_config  # pylint: disable=import-outside-toplevel
        encrypt, project_id = get_storage_config()
        content = json.dumps(self.metadata, indent=2).encode()
        if encrypt:
            from security.encryption import get_or_create_key, encrypt_bytes  # pylint: disable=import-outside-toplevel
            content = encrypt_bytes(content, get_or_create_key(project_id))
        os.makedirs(os.path.dirname(_meta_file()), exist_ok=True)
        with open(_meta_file(), "wb") as f:
            f.write(content)

    def save(self):
        """
        Saves the FAISS index and metadata to disk.
        Acquires a cross-process file lock so concurrent MCP server writes
        (e.g. Claude + Gemini both calling store_memory at the same time)
        do not corrupt the FAISS binary or metadata JSON.
        """
        with store_lock():
            faiss.write_index(self.index, _index_file())
            self._save_meta()

    def add(self, vector, text, importance, source: str = "memory", behaviour_score: float = 0.0):
        """
        Adds a new vector and its associated metadata to the database.
        source — "memory" for episodic/semantic memories, "symbol" for code symbols.
        """
        vector = np.array([vector]).astype("float32")

        self.index.add(vector)

        self.metadata.append({
            "text": text,
            "importance": importance,
            "source": source,
            "behaviour_score": behaviour_score,
        })

        self.save()

    def update_behaviour_score(self, row_id: int, new_score: float) -> bool:
        """Update behaviour_score for an existing entry by row index."""
        if row_id < 0 or row_id >= len(self.metadata):
            return False
        self.metadata[row_id]["behaviour_score"] = float(new_score)
        self._save_meta()
        return True

    def deprecate_row(self, faiss_row: int) -> bool:
        """
        Soft-delete a vector by row index.
        The FAISS index is not rebuilt; the metadata entry is flagged so search
        results skip it.  Returns True if the row was found and updated.
        """
        if faiss_row < 0 or faiss_row >= len(self.metadata):
            return False
        self.metadata[faiss_row]["deprecated"] = True
        self._save_meta()
        return True

    def suppress_row(self, faiss_row: int, reason: str = "auto_superseded", similarity: float = 1.0) -> bool:
        """
        Auto-suppress a vector row — distinct from user-initiated deprecate_row().

        Marks the entry as suppressed=True so it is excluded from all searches,
        then enqueues it in CleanupQueue for deferred hard-deletion by the cron
        cleanup job.  The FAISS index is not rebuilt immediately.

        Returns True if the row was found and updated.
        """
        if faiss_row < 0 or faiss_row >= len(self.metadata):
            return False
        entry = self.metadata[faiss_row]
        if entry.get("suppressed") or entry.get("deprecated"):
            return False  # already suppressed/deprecated
        entry["suppressed"] = True
        entry["suppress_reason"] = reason
        entry["suppressed_at"] = _now_iso()
        self._save_meta()
        # Enqueue for priority-queue cleanup
        try:
            from memory.cleanup_queue import CleanupQueue  # pylint: disable=import-outside-toplevel
            CleanupQueue().push(
                entry_id=faiss_row,
                store="semantic",
                importance=float(entry.get("importance", 0.5)),
                suppressed_at=entry["suppressed_at"],
                similarity_score=float(similarity),
            )
        except Exception:  # pylint: disable=broad-except
            pass  # queue is best-effort
        return True

    def search(self, vector, k=5, source: str | None = None):
        """
        Searches for the k most similar vectors to the given query vector.
        source — optional filter: "memory" | "symbol". None means no filter.
        Deprecated entries are never returned.
        """
        vector = np.array([vector]).astype("float32")

        # fetch more candidates when filtering so we still return up to k
        fetch_k = min(k * 3 if source else k, self.index.ntotal) if self.index.ntotal > 0 else 0
        if fetch_k == 0:
            return []

        _, indices = self.index.search(vector, fetch_k)

        results = []
        for i in indices[0]:
            if i < len(self.metadata):
                record = self.metadata[i]
                if record.get("deprecated", False) or record.get("suppressed", False):
                    continue
                # entries without a "source" field are legacy memories
                if source and record.get("source", "memory") != source:
                    continue
                results.append(record)
                if len(results) == k:
                    break

        return results

    def search_with_scores(self, vector, k=5, source: str | None = None):
        """
        Like search() but each result also includes 'l2_distance' and 'faiss_row'.
        Used by HybridRetriever to compute vector_score = max(0, 1 - dist/2).
        source — optional filter: "memory" | "symbol". None means no filter.
        Deprecated entries are never returned.
        """
        vector = np.array([vector]).astype("float32")

        fetch_k = min(k * 3 if source else k, self.index.ntotal) if self.index.ntotal > 0 else 0
        if fetch_k == 0:
            return []

        distances, indices = self.index.search(vector, fetch_k)
        results = []
        for dist, i in zip(distances[0], indices[0]):
            if 0 <= i < len(self.metadata):
                record = self.metadata[i]
                if record.get("deprecated", False) or record.get("suppressed", False):
                    continue
                if source and record.get("source", "memory") != source:
                    continue
                entry = dict(record)
                entry["l2_distance"] = float(dist)
                entry["faiss_row"] = int(i)
                l2_score = max(0.0, 1.0 - float(dist) / 2.0)
                b_score = float(record.get("behaviour_score", 0.0))
                entry["combined_score"] = round(l2_score * 0.8 + b_score * 0.2, 4)
                results.append(entry)
                if len(results) == k:
                    break
        return results

    def remove(self, ids: list[int]) -> None:
        """Soft-remove via deprecate_row — FAISS does not support in-place deletion."""
        import logging  # pylint: disable=import-outside-toplevel
        _log = logging.getLogger(__name__)
        for row_id in ids:
            if not self.deprecate_row(row_id):
                _log.warning("LocalVectorDB.remove(): row %d out of range", row_id)

    def persist(self) -> None:
        """Flush index + metadata to disk."""
        self.save()
