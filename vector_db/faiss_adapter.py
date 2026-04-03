# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
vector_db/faiss_adapter.py — VectorStorageAdapter backed by LocalVectorDB (FAISS).

This is the default backend when config.json does not specify vector_backend,
or when vector_backend == "faiss".
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from vector_db.adapter import VectorStorageAdapter
from vector_db.local_vector_db import LocalVectorDB

log = logging.getLogger(__name__)


class FAISSAdapter(VectorStorageAdapter):
    """Thin wrapper around LocalVectorDB that satisfies VectorStorageAdapter."""

    def __init__(self, dim: int = 384) -> None:
        self._db = LocalVectorDB(dim=dim)

    def add(
        self,
        vector: np.ndarray,
        text: str,
        importance: float,
        source: str = "memory",
    ) -> None:
        self._db.add(vector, text, importance, source)

    def search(
        self,
        vector: np.ndarray,
        top_k: int = 5,
        source: Optional[str] = None,
    ) -> list[dict]:
        return self._db.search(vector, top_k, source)

    def search_with_scores(
        self,
        vector: np.ndarray,
        top_k: int = 5,
        source: Optional[str] = None,
    ) -> list[dict]:
        return self._db.search_with_scores(vector, top_k, source)

    def remove(self, ids: list[int]) -> None:
        # IndexFlatL2 (used by LocalVectorDB) does not support remove_ids().
        # The AST FAISS (IndexIDMap2) handles its own removal — this adapter
        # wraps only the semantic memory FAISS, which does not need per-ID removal.
        log.warning(
            "FAISSAdapter.remove() is a no-op: IndexFlatL2 does not support "
            "ID-based removal. Use ASTIndexer for symbol-level removal."
        )

    def persist(self) -> None:
        self._db.save()
