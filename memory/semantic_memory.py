# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Module for managing and retrieving semantic memories using vector embeddings.
"""
import logging

from vector_db.local_vector_db import LocalVectorDB
from memory.embeddings import get_model

logger = logging.getLogger(__name__)


class SemanticMemory:
    """
    Handles storing and retrieving semantic memories.
    """
    def __init__(self):
        """
        Initialize the embedding model and vector database.
        """
        self.model = get_model()
        self.db = LocalVectorDB()

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
        vector = self.model.encode(text)

        importance = self.compute_importance(text)

        self.db.add(vector, text, importance)

        logger.debug("Stored semantic memory with importance: %s", importance)

    def retrieve(self, query: str, top_k: int = 5) -> list:
        """
        Search for memories similar to the query.
        """
        vector = self.model.encode(query)
        return self.db.search(vector, k=top_k)
