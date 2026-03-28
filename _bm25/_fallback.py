# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Pure-Python BM25 implementation — always available, zero extra deps.

This is the automatic fallback when the compiled C++ extension (_bm25_ext)
is not present.  The interface is identical to the C++ version so callers
never need to check which backend is active.

Algorithm: Okapi BM25
  score(d, q) = Σ_{t∈q}  IDF(t) · tf(t,d)·(k1+1) / (tf(t,d) + k1·(1−b+b·|d|/avgdl))
  IDF(t)      = log((N − df(t) + 0.5) / (df(t) + 0.5) + 1)   (Robertson–Spärck Jones)
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from collections import Counter


@dataclass
class Document:
    """A unit of text that can be indexed and retrieved."""
    id: str
    text: str


class BM25:
    """
    BM25 ranker over a fixed corpus of Documents.

    Usage::

        bm25 = BM25(k1=1.5, b=0.75)
        bm25.index([Document("d1", "the quick brown fox"),
                    Document("d2", "lazy dog")])
        results = bm25.search("quick fox", top_k=5)
        # → [("d1", 1.234), ("d2", 0.0)]
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._docs: list[Document] = []
        self._doc_lengths: list[int] = []
        self._avg_dl: float = 0.0
        # term → {doc_index: frequency}
        self._inverted: dict[str, dict[int, int]] = {}

    # ── public API ────────────────────────────────────────────────────────────

    def index(self, docs: list[Document]) -> None:
        """Build the inverted index from *docs*. Replaces any previous index."""
        self._docs = list(docs)
        self._doc_lengths = []
        self._inverted = {}

        for i, doc in enumerate(self._docs):
            tokens = _tokenize(doc.text)
            self._doc_lengths.append(len(tokens))
            counts = Counter(tokens)
            for term, freq in counts.items():
                self._inverted.setdefault(term, {})[i] = freq

        n = len(self._doc_lengths)
        self._avg_dl = sum(self._doc_lengths) / n if n else 0.0

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """
        Rank all indexed documents against *query*.

        Returns a list of (document_id, score) pairs sorted by descending
        score, clamped to min(top_k, len(docs)).
        """
        if not self._docs:
            return []

        query_terms = _tokenize(query)
        if not query_terms:
            return []

        n = len(self._docs)
        scores: dict[int, float] = {}

        for term in set(query_terms):
            postings = self._inverted.get(term)
            if not postings:
                continue
            df = len(postings)
            idf = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
            for doc_idx, tf in postings.items():
                dl = self._doc_lengths[doc_idx]
                denom = tf + self.k1 * (
                    1.0 - self.b + self.b * dl / self._avg_dl
                    if self._avg_dl > 0 else 1.0
                )
                scores[doc_idx] = scores.get(doc_idx, 0.0) + idf * tf * (self.k1 + 1.0) / denom

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        limit = max(0, min(top_k, n))
        return [(self._docs[i].id, score) for i, score in ranked[:limit]]


# ── tokenization ──────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase and split on non-alphanumeric characters."""
    return _TOKEN_RE.findall(text.lower())
