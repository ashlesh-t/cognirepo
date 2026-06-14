# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
CleanupQueue — persisted min-heap for auto-suppressed store entries.

When AutoStore suppresses an existing memory (because a newer, similar one
replaces it), the old entry is enqueued here with a deletion priority score.
The cron cleanup job (`cron/prune_memory.cleanup_suppressed`) drains the queue
in priority order and hard-deletes entries, then triggers a FAISS rebuild when
the fraction of dead rows exceeds the rebuild threshold.

Priority formula (higher = delete sooner):
    priority = 0.4*(age_days/30) + 0.3*(1-importance) + 0.3*similarity_score

Persisted at: .cognirepo/cron/cleanup_queue.json
Format: list of item dicts, kept sorted ascending by priority so the last N
items are always the highest-priority ones.

Thread safety: uses a file lock from config.lock so concurrent MCP server
processes don't corrupt the queue JSON.
"""
from __future__ import annotations

import heapq
import json
import logging
import os
from datetime import datetime, timezone

from config.paths import get_path
from config.lock import store_lock

log = logging.getLogger(__name__)

_QUEUE_FILE = "cron/cleanup_queue.json"


def _queue_path() -> str:
    return get_path(_QUEUE_FILE)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _days_since(iso_ts: str) -> float:
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(tz=timezone.utc) - dt).total_seconds() / 86400)
    except (ValueError, TypeError):
        return 0.0


class CleanupQueue:
    """
    Persisted min-heap of auto-suppressed entries awaiting hard deletion.

    Items are stored as dicts; internally ranked by `priority` (float).
    Lower priority = delete first (min-heap semantics).
    """

    def push(
        self,
        entry_id: int | str,
        store: str,
        importance: float,
        suppressed_at: str,
        similarity_score: float,
    ) -> None:
        """
        Add an entry to the cleanup queue.

        entry_id       — FAISS row index (semantic) or record id (episodic/learning)
        store          — "semantic" | "episodic" | "learning"
        importance     — original importance score of the suppressed entry (0–1)
        suppressed_at  — ISO timestamp when suppression happened
        similarity_score — cosine similarity to the superseding entry (0–1)
        """
        priority = self._compute_priority(
            suppressed_at=suppressed_at,
            importance=importance,
            similarity_score=similarity_score,
        )
        item = {
            "entry_id": entry_id,
            "store": store,
            "importance": importance,
            "suppressed_at": suppressed_at,
            "similarity_score": similarity_score,
            "priority": priority,
        }
        with store_lock():
            items = self._load()
            items.append(item)
            heapq.heapify(items)  # re-heapify after append (list-of-dicts by priority)
            self._save(items)

    def pop_batch(self, n: int = 50) -> list[dict]:
        """
        Pop up to n highest-priority items (those with highest priority score).
        Returns the popped items. Persists the remainder.
        """
        with store_lock():
            items = self._load()
            if not items:
                return []
            # Sort descending by priority so we pop from the end (highest priority first)
            items.sort(key=lambda x: x.get("priority", 0.0))
            popped = items[-n:]
            remaining = items[:-n]
            self._save(remaining)
        return popped

    def __len__(self) -> int:
        return len(self._load())

    # ── persistence ───────────────────────────────────────────────────────────

    def _load(self) -> list[dict]:
        path = _queue_path()
        if not os.path.exists(path):
            return []
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, items: list[dict]) -> None:
        path = _queue_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2)

    # ── priority formula ──────────────────────────────────────────────────────

    @staticmethod
    def _compute_priority(
        suppressed_at: str,
        importance: float,
        similarity_score: float,
        max_age_days: float = 30.0,
    ) -> float:
        """
        priority = 0.4*(age_days/max_age) + 0.3*(1-importance) + 0.3*similarity

        Higher score = should be deleted sooner.
        - Old entries: higher age contribution
        - Low importance: we lose less by deleting
        - High similarity to superseder: definitely redundant
        """
        age = min(_days_since(suppressed_at) / max_age_days, 1.0)
        low_importance = max(0.0, 1.0 - float(importance))
        sim = max(0.0, min(1.0, float(similarity_score)))
        return 0.4 * age + 0.3 * low_importance + 0.3 * sim
