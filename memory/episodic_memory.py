# pylint: disable=duplicate-code
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Functions for logging and managing episodic memory.

Search uses BM25Okapi (rank_bm25) for TF-IDF-weighted ranking.
The BM25 corpus is cached in-process and invalidated on every write.
"""
import json
import os
import re
from datetime import datetime

from config.paths import get_path

# ── BM25 module-level cache ───────────────────────────────────────────────────
# (event_id, tokenized_text) pairs built on first search; cleared on _save()
_BM25_CORPUS: list[tuple[str, list[str]]] | None = None
_BM25_INDEX: object | None = None  # BM25Okapi instance, or None when corpus empty


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase words of length ≥ 3."""
    return [w for w in re.findall(r"\w+", text.lower()) if len(w) >= 3]


def _file_path() -> str:
    return get_path("memory/episodic.json")


def _load() -> list:
    path = _file_path()
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return []
    with open(path, "rb") as f:
        raw = f.read()
    from security import get_storage_config  # pylint: disable=import-outside-toplevel
    encrypt, project_id = get_storage_config()
    if encrypt:
        from security.encryption import get_or_create_key, decrypt_bytes  # pylint: disable=import-outside-toplevel
        raw = decrypt_bytes(raw, get_or_create_key(project_id))
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def _save(data: list) -> None:
    global _BM25_CORPUS, _BM25_INDEX  # pylint: disable=global-statement
    from security import get_storage_config  # pylint: disable=import-outside-toplevel
    encrypt, project_id = get_storage_config()
    content = json.dumps(data, indent=2).encode()
    if encrypt:
        from security.encryption import get_or_create_key, encrypt_bytes  # pylint: disable=import-outside-toplevel
        content = encrypt_bytes(content, get_or_create_key(project_id))
    path = _file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    # Invalidate BM25 cache so the next search reflects the updated corpus
    _BM25_CORPUS = None
    _BM25_INDEX = None


def _get_bm25(data: list):
    """Return (BM25Okapi instance, event_id_list), building from cache if available."""
    global _BM25_CORPUS, _BM25_INDEX  # pylint: disable=global-statement
    if _BM25_INDEX is not None and _BM25_CORPUS is not None:
        return _BM25_INDEX, [eid for eid, _ in _BM25_CORPUS]

    from rank_bm25 import BM25Okapi  # pylint: disable=import-outside-toplevel
    corpus: list[list[str]] = []
    event_ids: list[str] = []
    for entry in data:
        text = entry.get("event", "") + " " + json.dumps(entry.get("metadata", {}))
        corpus.append(_tokenize(text))
        event_ids.append(entry["id"])

    if not corpus:
        return None, []

    _BM25_INDEX = BM25Okapi(corpus)
    _BM25_CORPUS = list(zip(event_ids, corpus))
    return _BM25_INDEX, event_ids


def log_event(event: str, metadata: dict = None) -> None:
    """
    Append an event (with optional metadata) to the episodic memory store.
    """
    data = _load()
    entry = {
        "id": f"e_{len(data)}",
        "event": event,
        "metadata": metadata or {},
        "time": datetime.utcnow().isoformat() + "Z",
    }
    if data:
        entry["prev"] = data[-1]["id"]
    data.append(entry)
    _save(data)


def get_history(limit: int = 100) -> list:
    """
    Return the last `limit` episodic events.
    """
    data = _load()
    return data[-limit:]


def search_episodes(query: str, limit: int = 10) -> list:
    """
    Search episodic events using BM25Okapi (TF-IDF-weighted) ranking.

    Episodes with the highest BM25 score for the query tokens are returned
    first.  Episodes with score 0 (no query term present) are excluded.
    """
    data = _load()
    if not data:
        return []

    tokens = _tokenize(query)
    if not tokens:
        return []

    bm25, event_ids = _get_bm25(data)
    if bm25 is None:
        return []

    scores = bm25.get_scores(tokens)
    ranked = sorted(
        ((score, eid) for score, eid in zip(scores, event_ids) if score > 0),
        key=lambda x: x[0],
        reverse=True,
    )

    id_to_entry = {e["id"]: e for e in data}
    return [id_to_entry[eid] for _, eid in ranked[:limit] if eid in id_to_entry]


def mark_stale(file_path: str) -> int:
    """
    Tag all episodic entries that reference file_path as stale.

    Episodes are NOT deleted — the historical record is preserved and
    remains queryable.  Entries are marked with:
        {"stale": True, "stale_reason": "file_deleted"}

    Returns the count of entries tagged.
    """
    data = _load()
    tagged = 0
    for entry in data:
        if entry.get("stale"):
            continue
        combined = entry.get("event", "") + json.dumps(entry.get("metadata", {}))
        if file_path in combined:
            entry["stale"] = True
            entry["stale_reason"] = "file_deleted"
            tagged += 1
    if tagged:
        _save(data)
    return tagged
