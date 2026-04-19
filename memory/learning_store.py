# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Dual-scope learning store for CogniRepo.

Scopes
------
project  — .cognirepo/learnings/   (code decisions, prod issues for this repo)
global   — ~/.cognirepo/learnings/ (AI-behaviour corrections, dev preferences)

The CompositeLearningStore merges both scopes at query time, ranking by
relevance + recency.

Learning types
--------------
correction   — "Mistake: used X, correct is Y"
prod_issue   — "Prod issue reported: feature A had race condition"
decision     — "We decided to use async db calls throughout"

Auto-tagger
-----------
auto_tag(text) scans for signal phrases and returns (type, scope) or
(None, None) if no learning is detected.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── signal phrases ────────────────────────────────────────────────────────────

_CORRECTION_SIGNALS = {
    "mistake", "correction", "corrected", "wrong approach", "incorrect",
    "don't do this", "fixed:", "fix:", "bug fix", "fixed a bug",
}
_PROD_ISSUE_SIGNALS = {
    "prod issue", "production issue", "reported", "root cause", "incident",
    "outage", "regression", "prod bug", "in production",
}
_DECISION_SIGNALS = {
    "we decided", "decided to", "decision:", "we chose", "going with",
    "our approach", "architecture decision", "adr:",
}

# Signals that indicate global scope (AI behaviour / developer preferences)
_GLOBAL_SIGNALS = {
    "prefer", "always use", "never use", "style", "convention",
    "claude", "gemini", "cursor", "ai model", "model preference",
    "developer preference", "dev preference",
}


def auto_tag(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Classify text as a learning and determine its scope.

    Returns (type, scope) where:
      type  ∈ {"correction", "prod_issue", "decision"} | None
      scope ∈ {"project", "global"} | None

    Returns (None, None) if no learning signal is detected.
    """
    lower = text.lower()

    learning_type: Optional[str] = None
    for signal in _CORRECTION_SIGNALS:
        if signal in lower:
            learning_type = "correction"
            break
    if learning_type is None:
        for signal in _PROD_ISSUE_SIGNALS:
            if signal in lower:
                learning_type = "prod_issue"
                break
    if learning_type is None:
        for signal in _DECISION_SIGNALS:
            if signal in lower:
                learning_type = "decision"
                break

    if learning_type is None:
        return None, None

    # Determine scope
    scope = "project"
    for signal in _GLOBAL_SIGNALS:
        if signal in lower:
            scope = "global"
            break
    # AI-behaviour corrections are always global
    if learning_type == "correction":
        for signal in ["ai model", "claude", "gemini", "cursor", "model"]:
            if signal in lower:
                scope = "global"
                break

    return learning_type, scope


# ── storage backend ───────────────────────────────────────────────────────────

class _LearningBackend:
    """File-based learning store under a given root directory."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _index_path(self) -> Path:
        return self._root / "learnings.json"

    def _load(self) -> list[dict]:
        path = self._index_path()
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, records: list[dict]) -> None:
        self._index_path().write_text(
            json.dumps(records, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def store(self, learning_type: str, text: str, metadata: dict, scope: str) -> str:
        """Persist a learning record; returns its ID."""
        records = self._load()
        record_id = uuid.uuid4().hex
        record = {
            "id": record_id,
            "type": learning_type,
            "scope": scope,
            "text": text,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            **metadata,
        }
        records.append(record)
        self._save(records)
        logger.debug("Stored learning %s (type=%s scope=%s)", record_id, learning_type, scope)
        return record_id

    def deprecate(self, record_id: str) -> bool:
        """
        Soft-delete a learning by ID.  Returns True if the record was found.
        Deprecated records are excluded from all future retrieve() calls.
        """
        records = self._load()
        updated = False
        for r in records:
            if r.get("id") == record_id and not r.get("deprecated", False):
                r["deprecated"] = True
                r["deprecated_at"] = datetime.now(tz=timezone.utc).isoformat()
                updated = True
                break
        if updated:
            self._save(records)
        return updated

    def detect_conflicts(self, text: str, top_k: int = 3) -> list[dict]:
        """
        Return existing non-deprecated learnings with significant word overlap to
        *text*.  Used to surface potential contradictions before a new learning is
        stored — the caller decides whether a real conflict exists.

        A record is returned when its word-overlap ratio with *text* exceeds 0.3.
        """
        records = self._load()
        records = [r for r in records if not r.get("deprecated", False)]

        words = set(text.lower().split())
        scored: list[tuple[float, dict]] = []
        for r in records:
            existing_words = set(r.get("text", "").lower().split())
            overlap = len(words & existing_words) / max(len(words), 1)
            if overlap > 0.3:
                scored.append((overlap, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:top_k]]

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        types: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        Return up to top_k learning records matching the query.
        Filtered by type if provided.  Ranked by recency (newest first)
        then simple substring relevance.  Deprecated records are excluded.
        """
        records = self._load()
        records = [r for r in records if not r.get("deprecated", False)]
        if types:
            records = [r for r in records if r.get("type") in types]

        query_lower = query.lower()
        scored: list[tuple[float, dict]] = []
        for r in records:
            text_lower = r.get("text", "").lower()
            # Simple relevance: count query-word hits
            words = query_lower.split()
            hits = sum(1 for w in words if w in text_lower)
            relevance = hits / max(len(words), 1)
            # Recency bonus
            try:
                ts = datetime.fromisoformat(r.get("timestamp", "2000-01-01"))
                days_ago = (datetime.now(tz=timezone.utc) - ts).days
            except (ValueError, TypeError):
                days_ago = 365
            recency = 1.0 / (1.0 + days_ago)
            scored.append((relevance * 0.7 + recency * 0.3, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:top_k]]


# ── public stores ─────────────────────────────────────────────────────────────

class ProjectLearningStore:
    """Stores learnings scoped to a single project's .cognirepo/learnings/."""

    def __init__(self, project_dir: Optional[str] = None) -> None:
        if project_dir:
            root = Path(project_dir) / ".cognirepo" / "learnings"
        else:
            from config.paths import get_path  # pylint: disable=import-outside-toplevel
            root = Path(get_path("learnings"))
        self._backend = _LearningBackend(root)

    def store_learning(
        self,
        learning_type: str,
        text: str,
        metadata: Optional[dict] = None,
    ) -> str:
        return self._backend.store(learning_type, text, metadata or {}, scope="project")

    def retrieve_learnings(
        self,
        query: str,
        top_k: int = 5,
        types: Optional[list[str]] = None,
    ) -> list[dict]:
        return self._backend.retrieve(query, top_k, types)

    def deprecate_learning(self, record_id: str) -> bool:
        """Soft-delete a learning by ID. Returns True if found."""
        return self._backend.deprecate(record_id)

    def supersede_learning(
        self,
        old_id: str,
        new_text: str,
        learning_type: str,
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        Deprecate *old_id* and immediately store *new_text* as its replacement.
        The new record carries a ``supersedes`` field pointing at *old_id*.
        Returns ``{"found_old": bool, "new_id": str}``.
        """
        found = self._backend.deprecate(old_id)
        meta = dict(metadata or {})
        meta["supersedes"] = old_id
        new_id = self._backend.store(learning_type, new_text, meta, scope="project")
        return {"found_old": found, "new_id": new_id}

    def detect_conflicts(self, text: str, top_k: int = 3) -> list[dict]:
        """Return existing learnings with high word-overlap to *text*."""
        return self._backend.detect_conflicts(text, top_k)


class GlobalLearningStore:
    """Stores learnings in ~/.cognirepo/learnings/ (cross-project)."""

    def __init__(self) -> None:
        global_dir = os.environ.get(
            "COGNIREPO_GLOBAL_DIR",
            str(Path.home() / ".cognirepo"),
        )
        root = Path(global_dir) / "learnings"
        self._backend = _LearningBackend(root)

    def store_learning(
        self,
        learning_type: str,
        text: str,
        metadata: Optional[dict] = None,
    ) -> str:
        return self._backend.store(learning_type, text, metadata or {}, scope="global")

    def retrieve_learnings(
        self,
        query: str,
        top_k: int = 5,
        types: Optional[list[str]] = None,
    ) -> list[dict]:
        return self._backend.retrieve(query, top_k, types)

    def deprecate_learning(self, record_id: str) -> bool:
        """Soft-delete a learning by ID. Returns True if found."""
        return self._backend.deprecate(record_id)

    def supersede_learning(
        self,
        old_id: str,
        new_text: str,
        learning_type: str,
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        Deprecate *old_id* and immediately store *new_text* as its replacement.
        Returns ``{"found_old": bool, "new_id": str}``.
        """
        found = self._backend.deprecate(old_id)
        meta = dict(metadata or {})
        meta["supersedes"] = old_id
        new_id = self._backend.store(learning_type, new_text, meta, scope="global")
        return {"found_old": found, "new_id": new_id}

    def detect_conflicts(self, text: str, top_k: int = 3) -> list[dict]:
        """Return existing learnings with high word-overlap to *text*."""
        return self._backend.detect_conflicts(text, top_k)


class CompositeLearningStore:
    """Merges project + global learnings and re-ranks by relevance + recency."""

    def __init__(
        self,
        project_dir: Optional[str] = None,
    ) -> None:
        self._project = ProjectLearningStore(project_dir)
        self._global = GlobalLearningStore()

    def store_learning(
        self,
        learning_type: str,
        text: str,
        metadata: Optional[dict] = None,
        scope: str = "auto",
    ) -> dict[str, str]:
        """Store to the appropriate scope (auto-detect or explicit)."""
        if scope == "auto":
            _, detected_scope = auto_tag(text)
            scope = detected_scope or "project"

        meta = metadata or {}
        if scope == "global":
            record_id = self._global.store_learning(learning_type, text, meta)
        else:
            record_id = self._project.store_learning(learning_type, text, meta)
        return {"id": record_id, "scope": scope}

    def retrieve_learnings(
        self,
        query: str,
        top_k: int = 5,
        types: Optional[list[str]] = None,
        scopes: Optional[list[str]] = None,
    ) -> list[dict]:
        """Retrieve from both scopes, merge, and re-rank."""
        scopes = scopes or ["project", "global"]
        results: list[dict] = []
        if "project" in scopes:
            results.extend(self._project.retrieve_learnings(query, top_k, types))
        if "global" in scopes:
            results.extend(self._global.retrieve_learnings(query, top_k, types))

        # De-duplicate by id, then re-rank by timestamp (newest first)
        seen: set[str] = set()
        unique = []
        for r in results:
            rid = r.get("id", "")
            if rid not in seen:
                seen.add(rid)
                unique.append(r)

        unique.sort(
            key=lambda r: r.get("timestamp", "2000-01-01"),
            reverse=True,
        )
        return unique[:top_k]

    def deprecate_learning(self, record_id: str) -> dict:
        """
        Soft-delete a learning by ID, searching project scope first then global.
        Returns ``{"found": bool, "scope": "project"|"global"|None}``.
        """
        if self._project.deprecate_learning(record_id):
            return {"found": True, "scope": "project"}
        if self._global.deprecate_learning(record_id):
            return {"found": True, "scope": "global"}
        return {"found": False, "scope": None}

    def supersede_learning(
        self,
        old_id: str,
        new_text: str,
        learning_type: str,
        metadata: Optional[dict] = None,
        scope: str = "auto",
    ) -> dict:
        """
        Deprecate *old_id* (found in either scope) and store *new_text* as its
        replacement.  The replacement scope is auto-detected from the text unless
        *scope* is explicit.

        Returns ``{"found_old": bool, "new_id": str, "scope": str}``.
        """
        # Deprecate the old record from whichever scope holds it
        dep_result = self.deprecate_learning(old_id)

        # Determine target scope for the replacement
        if scope == "auto":
            _, detected = auto_tag(new_text)
            target_scope = detected or "project"
        else:
            target_scope = scope

        meta = dict(metadata or {})
        meta["supersedes"] = old_id

        # Store replacement directly via the backend (old_id already deprecated above)
        if target_scope == "global":
            new_id = self._global._backend.store(learning_type, new_text, meta, scope="global")
        else:
            new_id = self._project._backend.store(learning_type, new_text, meta, scope="project")

        return {
            "found_old": dep_result["found"],
            "new_id": new_id,
            "scope": target_scope,
        }

    def detect_conflicts(self, text: str, top_k: int = 3) -> list[dict]:
        """
        Return existing learnings (from both scopes) with high word-overlap to
        *text*.  De-duplicated and ranked by overlap.
        """
        seen: set[str] = set()
        combined: list[dict] = []
        for record in (
            self._project.detect_conflicts(text, top_k)
            + self._global.detect_conflicts(text, top_k)
        ):
            rid = record.get("id", "")
            if rid not in seen:
                seen.add(rid)
                combined.append(record)
        return combined[:top_k]


# ── module-level singleton ────────────────────────────────────────────────────

_STORE: Optional[CompositeLearningStore] = None
_STORE_LOCK = threading.Lock()


def get_learning_store() -> CompositeLearningStore:
    """Return the process-wide composite learning store (double-checked locking)."""
    global _STORE  # pylint: disable=global-statement
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                _STORE = CompositeLearningStore()
    return _STORE
