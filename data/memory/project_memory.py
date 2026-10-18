# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
memory/project_memory.py — Shared FAISS index for all repos in a project.

Each project gets its own vector store at:
  ~/.cognirepo/projects/<org>/<project>/vector_db/

Memories stored here are visible to all repos linked to the same project,
enabling cross-repo knowledge sharing without manual context passing.
"""
from __future__ import annotations

import logging
from pathlib import Path

from core.config.lock import store_lock
from core.config.orgs import get_shared_memory_path
from core.config.safe_read import StoreUnreadableError
from data.memory.embeddings import encode_with_timeout

logger = logging.getLogger(__name__)


class ProjectMemory:
    """Shared vector store for all repos in a (org, project) pair."""

    def __init__(self, org: str, project: str) -> None:
        self._org = org
        self._project = project
        self._base = get_shared_memory_path(org, project)
        self._db = self._open_db()

    def _open_db(self):
        from core.vector_db.local_vector_db import LocalVectorDB  # pylint: disable=import-outside-toplevel
        import os  # pylint: disable=import-outside-toplevel
        # point LocalVectorDB at project-scoped paths
        idx_path = self._base / "vector_db" / "semantic.index"
        meta_path = self._base / "memory" / "semantic_metadata.json"
        os.makedirs(str(idx_path.parent), exist_ok=True)
        os.makedirs(str(meta_path.parent), exist_ok=True)
        # Monkey-patch path helpers for this instance via subclass
        return _ProjectLocalVectorDB(
            base=self._base, key_id=f"cognirepo-project-memory:{self._org}/{self._project}")

    def store(self, text: str, source_repo: str, importance: float = 0.7) -> None:
        """Embed text and store in shared project index."""
        try:
            vec = encode_with_timeout(text)
            self._db.add(vec, text, importance=importance, source=source_repo)
            logger.debug("ProjectMemory[%s/%s] stored from %s", self._org, self._project, source_repo)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("ProjectMemory.store() failed: %s", exc)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Search shared project memories for query."""
        try:
            vec = encode_with_timeout(query)
            return self._db.search(vec, k=top_k)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("ProjectMemory.search() failed: %s", exc)
            return []


class _ProjectLocalVectorDB:
    """LocalVectorDB variant that stores at a custom base path."""

    def __init__(self, base: Path, key_id: "str | None" = None) -> None:
        import faiss  # pylint: disable=import-outside-toplevel
        import json  # pylint: disable=import-outside-toplevel
        import os  # pylint: disable=import-outside-toplevel

        self._idx_file = str(base / "vector_db" / "semantic.index")
        self._meta_file = str(base / "memory" / "semantic_metadata.json")
        self._key_id = key_id  # shared by several repos → own keychain entry (#186)
        self.dim = 384

        if os.path.exists(self._idx_file):
            try:
                self.index = faiss.read_index(self._idx_file)
            except Exception:  # pylint: disable=broad-except
                self.index = faiss.IndexFlatL2(self.dim)
        else:
            self.index = faiss.IndexFlatL2(self.dim)

        self.metadata = []
        if os.path.exists(self._meta_file):
            try:
                self.metadata = self._read_meta()
            except StoreUnreadableError as exc:  # locked ciphertext: add() raises, never overwrites
                logger.warning("%s", exc)

    def _read_meta(self) -> list:
        import json  # pylint: disable=import-outside-toplevel
        from core.security.store_crypto import decode_store  # pylint: disable=import-outside-toplevel
        with open(self._meta_file, "rb") as f:
            return json.loads(decode_store(f.read(), self._meta_file, key_id=self._key_id))

    def _reload_locked(self) -> None:
        """Re-read index + metadata from disk. Caller holds store_lock().

        Strict: an unreadable file raises (store() logs and skips) instead of falling back to
        an empty in-memory store that the following write would persist over it (#135/#136)."""
        import faiss  # pylint: disable=import-outside-toplevel
        import json  # pylint: disable=import-outside-toplevel
        import os  # pylint: disable=import-outside-toplevel
        from core.config.safe_read import read_retry  # pylint: disable=import-outside-toplevel

        if os.path.exists(self._idx_file):
            self.index = read_retry(
                self._idx_file, lambda: faiss.read_index(self._idx_file), retry_on=(Exception,))
        else:
            self.index = faiss.IndexFlatL2(self.dim)
        if os.path.exists(self._meta_file):
            self.metadata = read_retry(self._meta_file, self._read_meta)
        else:
            self.metadata = []

    def add(self, vector, text: str, importance: float, source: str = "memory") -> None:
        import faiss  # pylint: disable=import-outside-toplevel
        import json  # pylint: disable=import-outside-toplevel
        import numpy as np  # pylint: disable=import-outside-toplevel

        vec = np.array([vector]).astype("float32")
        with store_lock():
            self._reload_locked()  # COGNIREPO-136: append to the CURRENT disk state, not our snapshot
            self.index.add(vec)
            self.metadata.append({"text": text, "importance": importance, "source": source})
            from core.config.atomic import atomic_path, atomic_write  # pylint: disable=import-outside-toplevel
            with atomic_path(self._idx_file) as _tmp:
                faiss.write_index(self.index, _tmp)
            from core.security.store_crypto import encode_store  # pylint: disable=import-outside-toplevel
            atomic_write(self._meta_file, encode_store(
                json.dumps(self.metadata, indent=2).encode("utf-8"), key_id=self._key_id))

    def search(self, vector, k: int = 5, source: str | None = None) -> list[dict]:
        import numpy as np  # pylint: disable=import-outside-toplevel

        if self.index.ntotal == 0:
            return []
        vec = np.array([vector]).astype("float32")
        fetch_k = min(k * 3 if source else k, self.index.ntotal)
        _, indices = self.index.search(vec, fetch_k)
        results = []
        for i in indices[0]:
            if 0 <= i < len(self.metadata):
                rec = self.metadata[i]
                if rec.get("deprecated") or rec.get("suppressed"):
                    continue
                if source and rec.get("source", "memory") != source:
                    continue
                results.append(rec)
                if len(results) == k:
                    break
        return results
