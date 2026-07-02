# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Tool to store a text memory into semantic memory.
"""
import logging
import sys
from data.memory.semantic_memory import SemanticMemory
from data.memory.episodic_memory import log_event
from core.metrics import MEMORY_OPS_TOTAL

logger = logging.getLogger(__name__)


def store_memory(text: str, source: str = "") -> dict:
    """
    Store a text memory in semantic memory and return status.

    Returns a ``conflicts`` list of existing memories that may contradict *text*
    (detected by word-overlap + numeral-change heuristics).  Callers can use
    ``supersede_learning`` to replace conflicting entries.
    """
    mem = SemanticMemory()
    importance = mem.compute_importance(text)

    # ── Conflict detection before storing ────────────────────────────────────
    # Search semantic memory for near-duplicate or value-contradicting entries.
    _TIME_UNITS = frozenset({
        "second", "seconds", "minute", "minutes", "hour", "hours",
        "day", "days", "week", "weeks", "month", "months",
        "ms", "millisecond", "milliseconds",
    })
    conflicts: list[dict] = []
    try:
        _new_words = set(text.lower().split())
        _existing = mem.search(text, top_k=5)
        for _hit in _existing:
            _hit_text = _hit.get("text", "")
            if not _hit_text:
                continue
            if " ".join(_hit_text.lower().split()) == " ".join(text.lower().split()):
                # Exact duplicate already stored — do not store again.
                # (Observed: identical memory persisted 3× across retries,
                # multiplying conflict/supersede churn downstream.)
                return {
                    "status": "deduplicated",
                    "text": text,
                    "source": source,
                    "importance": importance,
                    "existing_id": _hit.get("id", _hit.get("_id", "")),
                    "conflicts": [],
                }
            _hit_words = set(_hit_text.lower().split())
            _common = _new_words & _hit_words
            _overlap = len(_common) / max(len(_new_words), 1)
            if _overlap <= 0.3:
                continue
            # Classify: value_contradiction when the only differing tokens are
            # numbers or time units ("1 hour" → "30 minutes"); otherwise semantic_overlap.
            _diff = (_new_words | _hit_words) - _common
            if _diff and all(t.isdigit() or t in _TIME_UNITS for t in _diff):
                _conflict_type = "value_contradiction"
            else:
                _conflict_type = "semantic_overlap"
            conflicts.append({
                "id": _hit.get("id", _hit.get("_id", "")),
                "text": _hit_text,
                "score": round(_hit.get("score", 0.0), 4),
                "conflict_type": _conflict_type,
            })
    except Exception as _cf_exc:  # pylint: disable=broad-except
        logger.warning("conflict detection failed: %s", _cf_exc)

    try:
        mem.store(text)
        MEMORY_OPS_TOTAL.labels(op="store", result="ok").inc()
    except Exception:
        MEMORY_OPS_TOTAL.labels(op="store", result="error").inc()
        raise

    # Invalidate retrieval cache so the just-stored memory is visible immediately
    # on the next retrieve_memory call (cache TTL is 5 min — without this, a store
    # followed immediately by retrieve would return the pre-store snapshot).
    try:
        from intelligence.retrieval.hybrid import invalidate_hybrid_cache  # pylint: disable=import-outside-toplevel
        invalidate_hybrid_cache()
    except Exception:  # pylint: disable=broad-except
        pass

    # Log the event in episodic memory
    log_event(
        event=f"store-memory: {text[:50]}...",
        metadata={"source": source, "importance": importance, "type": "semantic_storage"}
    )

    # Mirror to shared project memory when autosave_context enabled
    try:
        from core.config.orgs import get_repo_project  # pylint: disable=import-outside-toplevel
        import os  # pylint: disable=import-outside-toplevel
        result = get_repo_project(os.getcwd())
        if result:
            from data.memory.project_memory import ProjectMemory  # pylint: disable=import-outside-toplevel
            org, project = result
            ProjectMemory(org, project).store(
                text,
                source_repo=os.path.basename(os.getcwd()),
                importance=importance,
            )
    except Exception as _mirror_exc:  # pylint: disable=broad-except
        logger.warning("project memory mirror failed (store succeeded): %s", _mirror_exc)

    return {
        "status": "stored",
        "text": text,
        "source": source,
        "importance": importance,
        "conflicts": conflicts,
    }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        _result = store_memory(sys.argv[1])
        print(_result)
    else:
        print("Usage: python tools/store_memory.py <text>")
