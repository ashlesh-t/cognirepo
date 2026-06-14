# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Module for managing and retrieving semantic memories using vector embeddings.
"""
import logging

from vector_db.factory import get_vector_adapter
from memory.embeddings import encode_with_timeout

logger = logging.getLogger(__name__)


class SemanticMemory:
    """
    Handles storing and retrieving semantic memories.
    """
    def __init__(self):
        """
        Initialize the vector database.
        """
        self.db = get_vector_adapter(dim=384)

    def compute_importance(self, text):
        """
        Calculates importance score based on length and keywords.
        """
        length_score = min(len(text) / 100, 1)

        keywords = ["bug", "fix", "error", "important"]

        keyword_score = 0

        for k in keywords:
            if k in text.lower():
                keyword_score += 0.2

        return min(length_score + keyword_score, 1)

    def store(self, text):
        """
        Store a text memory with its calculated importance.
        """
        vector = encode_with_timeout(text)

        importance = self.compute_importance(text)

        self.db.add(vector, text, importance)

        logger.debug("Stored semantic memory with importance: %s", importance)

    def retrieve(self, query: str, top_k: int = 5) -> list:
        """
        Search for memories similar to the query.
        """
        vector = encode_with_timeout(query)
        return self.db.search(vector, top_k=top_k)

    def search(self, query: str, top_k: int = 5) -> list:
        """Alias for retrieve() used by cross_repo and org search."""
        return self.retrieve(query, top_k=top_k)

    def deprecate(self, text: str) -> int:
        """
        Soft-delete all semantic memory entries whose text matches exactly.
        Returns the number of entries deprecated.
        """
        count = 0
        for i, record in enumerate(self.db.metadata):
            if record.get("text") == text and not record.get("deprecated", False):
                self.db.deprecate_row(i)
                count += 1
        return count
