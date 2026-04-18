# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
vector_db/adapter.py — Abstract base class for CogniRepo vector storage backends.

All concrete backends (FAISS, ChromaDB, …) must implement VectorStorageAdapter.
Tools should call get_storage_adapter() from vector_db/__init__.py to get the
configured backend — swapping backends requires only a config.json change.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np


class VectorStorageAdapter(ABC):
    """Abstract vector storage adapter.

    All methods receive/return plain dicts so adapters stay
    decoupled from concrete FAISS or ChromaDB types.
    """

    @abstractmethod
    def add(
        self,
        vector: np.ndarray,
        text: str,
        importance: float,
        source: str = "memory",
        behaviour_score: float = 0.0,
    ) -> None:
        """Add one vector with associated metadata."""

    @abstractmethod
    def update_behaviour_score(self, row_id: int, new_score: float) -> bool:
        """Update behaviour_score for an existing entry. Returns True on success."""

    @abstractmethod
    def search(
        self,
        vector: np.ndarray,
        top_k: int = 5,
        source: Optional[str] = None,
    ) -> list[dict]:
        """Return top_k results (dicts with at least 'text', 'importance', 'source').
        source — optional filter: "memory" | "symbol". None means no filter.
        """

    @abstractmethod
    def search_with_scores(
        self,
        vector: np.ndarray,
        top_k: int = 5,
        source: Optional[str] = None,
    ) -> list[dict]:
        """Like search() but each result also includes 'l2_distance' and 'faiss_row'."""

    @abstractmethod
    def remove(self, ids: list[int]) -> None:
        """Remove entries by integer index IDs.
        Best-effort: implementations that do not support removal should log a warning
        and return without raising.
        """

    @abstractmethod
    def persist(self) -> None:
        """Flush any in-memory state to the underlying storage medium."""
