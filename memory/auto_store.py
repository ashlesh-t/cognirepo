# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
AutoStore — novelty-gated automatic memory persistence.

When a high-value MCP tool (context_pack, semantic_search_code, who_calls, etc.)
returns results, the MCP server calls AutoStore.store_if_novel() to persist
novel findings into the semantic memory store.  This solves the re-discovery
problem: each session starts with accumulated knowledge from previous traversals
rather than a blank slate.

Two gates prevent noise:

1. Novelty gate (threshold 0.85):
   Embed the new text and search the existing store for the top-1 result.
   If cosine similarity > 0.85, the content is already known — skip.

2. Suppression (threshold 0.92):
   If an existing entry has cosine similarity > 0.92 to the new text, it is
   superseded.  Mark it as suppressed=True and enqueue for deletion by the
   cron cleanup job (CleanupQueue).

Importance scoring per tool:
   explain_change    → 0.75  (architectural insight)
   context_pack      → 0.70  (rich multi-source context)
   semantic_search   → 0.65  (code symbol discovery)
   who_calls         → 0.60  (call-graph knowledge)
   subgraph          → 0.60  (relationship knowledge)
   dependency_graph  → 0.60  (dependency knowledge)
   search_docs       → 0.55  (doc reference)

Entries are stored with source="auto_discovery" so they can be distinguished
from explicit store_memory() calls and pruned separately if needed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# ── similarity thresholds ─────────────────────────────────────────────────────
_NOVELTY_THRESHOLD = 0.85    # sim > this → skip (already known)
_SUPPRESS_THRESHOLD = 0.92   # sim > this → suppress old entry

# ── quality gates ─────────────────────────────────────────────────────────────
_MIN_IMPORTANCE = 0.30        # below this → don't bother storing
_MIN_TEXT_LEN = 50            # below this → too short to be useful

# ── per-tool importance defaults ─────────────────────────────────────────────
_TOOL_IMPORTANCE: dict[str, float] = {
    "explain_change":    0.75,
    "context_pack":      0.70,
    "semantic_search_code": 0.65,
    "who_calls":         0.60,
    "subgraph":          0.60,
    "dependency_graph":  0.60,
    "search_docs":       0.55,
}


def _sim_from_l2(l2_dist: float) -> float:
    """Convert L2 distance to cosine-like similarity: max(0, 1 - dist/2)."""
    return max(0.0, 1.0 - l2_dist / 2.0)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class AutoStore:
    """
    Novelty-gated auto-storage for MCP tool results.

    Instantiated per-call (lightweight — db and model are module-level singletons).
    """

    # ── public API ────────────────────────────────────────────────────────────

    def store_if_novel(
        self,
        text: str,
        source_tool: str,
        importance: float | None = None,
    ) -> bool:
        """
        Embed *text*, check novelty, suppress near-duplicates, and store if novel.
        Returns True if the entry was stored, False if skipped.
        """
        if not text or len(text) < _MIN_TEXT_LEN:
            return False

        eff_importance = importance if importance is not None else _TOOL_IMPORTANCE.get(source_tool, 0.5)
        if eff_importance < _MIN_IMPORTANCE:
            return False

        try:
            from memory.embeddings import encode_with_timeout  # pylint: disable=import-outside-toplevel
            from vector_db.local_vector_db import LocalVectorDB  # pylint: disable=import-outside-toplevel
        except ImportError as exc:
            log.debug("AutoStore: cannot import deps: %s", exc)
            return False

        from memory.embeddings import encode_with_timeout  # pylint: disable=import-outside-toplevel
        db = LocalVectorDB()

        vec = encode_with_timeout(text).astype("float32")

        # ── novelty gate ──────────────────────────────────────────────────────
        if not self._is_novel(db, vec):
            log.debug("AutoStore: skipping duplicate for tool=%s", source_tool)
            return False

        # ── suppress near-duplicates ──────────────────────────────────────────
        self._suppress_similar(db, vec, source_tool)

        # ── store ─────────────────────────────────────────────────────────────
        db.add(vec, text, importance=eff_importance, source="auto_discovery")
        log.debug("AutoStore: stored finding from tool=%s importance=%.2f", source_tool, eff_importance)
        return True

    @staticmethod
    def importance_for(tool_name: str, result) -> float:
        """
        Compute a result-aware importance score.

        For tools that return scored sections (context_pack), derive importance
        from the average section score.  Otherwise fall back to the tool default.
        """
        base = _TOOL_IMPORTANCE.get(tool_name, 0.5)
        try:
            if tool_name == "context_pack" and isinstance(result, dict):
                sections = result.get("sections", [])
                scores = [float(s.get("score", 0)) for s in sections if s.get("score")]
                if scores:
                    return min(1.0, sum(scores) / len(scores) + 0.1)
            if tool_name == "semantic_search_code" and isinstance(result, list) and result:
                top_score = float(result[0].get("score", base))
                return min(1.0, top_score)
        except Exception:  # pylint: disable=broad-except
            pass
        return base

    # ── internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _is_novel(db, vec) -> bool:
        """Return True if no existing entry has similarity > _NOVELTY_THRESHOLD."""
        if db.index.ntotal == 0:
            return True
        try:
            hits = db.search_with_scores(vec, k=1)
        except Exception:  # pylint: disable=broad-except
            return True
        if not hits:
            return True
        sim = _sim_from_l2(hits[0].get("l2_distance", 999.0))
        return sim <= _NOVELTY_THRESHOLD

    @staticmethod
    def _suppress_similar(db, vec, source_tool: str) -> None:
        """
        Find entries with similarity > _SUPPRESS_THRESHOLD and mark them suppressed.
        Enqueues them in CleanupQueue for deferred hard-deletion.
        """
        try:
            hits = db.search_with_scores(vec, k=5)
        except Exception:  # pylint: disable=broad-except
            return

        for hit in hits:
            sim = _sim_from_l2(hit.get("l2_distance", 999.0))
            if sim <= _SUPPRESS_THRESHOLD:
                continue
            faiss_row = hit.get("faiss_row")
            if faiss_row is None:
                continue
            # Don't suppress entries that are themselves auto-discoveries with higher importance
            existing_source = hit.get("source", "memory")
            existing_importance = float(hit.get("importance", 0.5))
            new_importance = _TOOL_IMPORTANCE.get(source_tool, 0.5)
            if existing_source == "auto_discovery" and existing_importance >= new_importance:
                continue
            db.suppress_row(faiss_row, reason=f"superseded_by_{source_tool}", similarity=sim)
