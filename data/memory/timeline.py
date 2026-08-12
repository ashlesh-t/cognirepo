# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
data/memory/timeline.py — COGNIREPO-204 unified timeline.

Merges three independently-written stores — episodic events (log_episode/
record_decision), session-exchange files (session_listener), and behaviour-tracked
error patterns — into one chronologically ordered view, plus a deterministic
template rollup (counts + top items; no model-generated text).

Replaces the get_session_history + episodic_search + get_error_patterns 3-call
stitch an agent previously had to do by hand to answer "what happened".
"""
from __future__ import annotations

import glob
import json
import os
import re
from datetime import datetime, timedelta, timezone

from core.config.paths import get_path
from data.memory.episodic_memory import _archive_path, _load as _load_episodic

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _parse_ts(raw: "str | None") -> datetime:
    """Normalize an ISO timestamp string for sorting/filtering.

    Some older entries lack a timezone suffix — treat those as UTC so they sort
    consistently against tz-aware entries instead of raising on comparison.
    Unparseable/missing timestamps sort first (oldest), not raise.
    """
    if not raw:
        return _EPOCH
    try:
        s = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return _EPOCH


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _parse_since(since: "str | None") -> datetime:
    """Parse a relative duration ("7d", "24h", "30m") or an ISO timestamp.
    Falls back to 7 days ago on anything unparseable.
    """
    now = _now()
    if not since:
        return now - timedelta(days=7)
    m = re.match(r"^(\d+)([dhm])$", since.strip())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"d": timedelta(days=n), "h": timedelta(hours=n), "m": timedelta(minutes=n)}[unit]
        return now - delta
    parsed = _parse_ts(since)
    return parsed if parsed is not _EPOCH else now - timedelta(days=7)


def parse_session_file(path: str) -> "dict | None":
    """Extract session_id/created_at/message_count/last_exchange from one session
    JSON file.

    Shared by get_session_history (interface/server/mcp_server.py) and the
    timeline merge — extracted here so both read one implementation instead of
    two independently-maintained copies of the same last-exchange parsing.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    messages = data.get("messages", [])
    last_exchange: dict = {}
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "assistant":
            last_exchange["assistant"] = messages[i].get("content", "")[:300]
        elif messages[i].get("role") == "user" and "assistant" in last_exchange:
            last_exchange["user"] = messages[i].get("content", "")[:300]
            break
    return {
        "session_id": data.get("session_id", os.path.basename(path)),
        "created_at": data.get("created_at"),
        "message_count": len(messages),
        "model": data.get("model", "unknown"),
        "last_exchange": last_exchange,
    }


def _list_session_files() -> list[str]:
    sessions_dir = get_path("sessions")
    if not os.path.isdir(sessions_dir):
        return []
    files = glob.glob(os.path.join(sessions_dir, "*.json"))
    return [f for f in files if not f.endswith("current.json")]


def _session_entries() -> list[dict]:
    entries = []
    for sf in sorted(_list_session_files()):  # fixed disk-order input for determinism
        parsed = parse_session_file(sf)
        if parsed is None or not parsed.get("created_at"):
            continue
        exch = parsed.get("last_exchange", {})
        summary = exch.get("user") or exch.get("assistant") or f"{parsed['message_count']} messages"
        entries.append({
            "ts": parsed["created_at"],
            "kind": "session",
            "summary": summary[:160],
            "ref": parsed["session_id"],
        })
    return entries


def _episodic_entries(include_archived: bool) -> list[dict]:
    data = list(_load_episodic())
    if include_archived:
        apath = _archive_path()
        if os.path.exists(apath):
            try:
                with open(apath, "rb") as f:
                    data = json.loads(f.read()) + data
            except (OSError, json.JSONDecodeError):
                pass
    entries = []
    for e in data:
        meta = e.get("metadata", {}) or {}
        kind = "decision" if meta.get("type") == "decision" else "episode"
        summary = meta.get("summary") or e.get("event", "")
        entries.append({
            "ts": e.get("time"),
            "kind": kind,
            "summary": summary[:160],
            "ref": e.get("id", ""),
        })
    return entries


def _error_entries() -> list[dict]:
    try:
        from data.graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        from data.graph.behaviour_tracker import BehaviourTracker  # pylint: disable=import-outside-toplevel
        patterns = BehaviourTracker(KnowledgeGraph()).get_error_patterns(min_count=1)
    except Exception:  # pylint: disable=broad-except
        return []
    return [
        {
            "ts": p.get("last_seen"),
            "kind": "error",
            "summary": f"{p['error_type']} (x{p['count']})",
            "ref": p["error_type"],
        }
        for p in patterns
        if p.get("last_seen")
    ]


def merge(since: str = "7d", include_archived: bool = False, limit: int = 100) -> list[dict]:
    """Return timeline entries — {ts, kind, summary, ref} — newest first.

    kind is one of: session, episode, decision, error. Entries older than
    `since` (a relative duration like "7d"/"24h"/"30m", or an ISO timestamp)
    are excluded. Deterministic: sorts by (timestamp desc, kind, ref) so ties
    (equal or missing timestamps) always resolve the same way for identical
    store state — required for byte-identical output (AC3).
    """
    cutoff = _parse_since(since)
    raw = _session_entries() + _episodic_entries(include_archived) + _error_entries()
    dated = [(e, _parse_ts(e.get("ts"))) for e in raw]
    dated = [(e, dt) for e, dt in dated if dt >= cutoff]
    dated.sort(key=lambda pair: (pair[1], pair[0]["kind"], pair[0]["ref"]), reverse=True)
    return [e for e, _ in dated[:limit]]


def rollup(entries: list[dict]) -> dict:
    """Deterministic template rollup over merge() output — counts + top items,
    no model-generated text. Foundation for EPIC-300's insights report.
    """
    counts: dict[str, int] = {}
    decisions: list[str] = []
    errors: list[str] = []
    for e in entries:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
        if e["kind"] == "decision":
            decisions.append(e["summary"])
        elif e["kind"] == "error":
            errors.append(e["summary"])
    return {
        "total": len(entries),
        "counts": counts,
        "top_decisions": decisions[:3],
        "top_errors": errors[:3],
    }
