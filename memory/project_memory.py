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

from config.lock import store_lock
from config.orgs import get_shared_memory_path
from memory.embeddings import encode_with_timeout

logger = logging.getLogger(__name__)


class ProjectMemory:
    """Shared vector store for all repos in a (org, project) pair."""

    def __init__(self, org: str, project: str) -> None:
        self._org = org
        self._project = project
        self._base = get_shared_memory_path(org, project)
        self._db = self._open_db()

    def _open_db(self):
        from vector_db.local_vector_db import LocalVectorDB  # pylint: disable=import-outside-toplevel
        import os  # pylint: disable=import-outside-toplevel
        # point LocalVectorDB at project-scoped paths
        idx_path = self._base / "vector_db" / "semantic.index"
        meta_path = self._base / "memory" / "semantic_metadata.json"
        os.makedirs(str(idx_path.parent), exist_ok=True)
        os.makedirs(str(meta_path.parent), exist_ok=True)
        # Monkey-patch path helpers for this instance via subclass
        return _ProjectLocalVectorDB(base=self._base)

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

    def __init__(self, base: Path) -> None:
        import faiss  # pylint: disable=import-outside-toplevel
        import json  # pylint: disable=import-outside-toplevel
        import os  # pylint: disable=import-outside-toplevel

        self._idx_file = str(base / "vector_db" / "semantic.index")
        self._meta_file = str(base / "memory" / "semantic_metadata.json")
        self.dim = 384

        if os.path.exists(self._idx_file):
            try:
                self.index = faiss.read_index(self._idx_file)
            except Exception:  # pylint: disable=broad-except
                self.index = faiss.IndexFlatL2(self.dim)
        else:
            self.index = faiss.IndexFlatL2(self.dim)

        if os.path.exists(self._meta_file):
            with open(self._meta_file, encoding="utf-8") as f:
                self.metadata = json.load(f)
        else:
            self.metadata = []

    def add(self, vector, text: str, importance: float, source: str = "memory") -> None:
        import faiss  # pylint: disable=import-outside-toplevel
        import json  # pylint: disable=import-outside-toplevel
        import numpy as np  # pylint: disable=import-outside-toplevel

        vec = np.array([vector]).astype("float32")
        with store_lock():
            self.index.add(vec)
            self.metadata.append({"text": text, "importance": importance, "source": source})
            faiss.write_index(self.index, self._idx_file)
            with open(self._meta_file, "w", encoding="utf-8") as f:
                json.dump(self.metadata, f, indent=2)

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
