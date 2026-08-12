# pylint: disable=duplicate-code
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Functions for logging and managing episodic memory.

Search uses BM25Okapi (rank_bm25) for TF-IDF-weighted ranking.
The BM25 corpus is cached in-process and invalidated on every write.
"""
import json
import logging
import os
import re
import threading
from collections import Counter
from datetime import datetime, timezone

from core.config.paths import get_path

logger = logging.getLogger(__name__)

# ── episodic memory size cap ──────────────────────────────────────────────────
_MAX_EVENTS_DEFAULT = 10_000
_ARCHIVE_FRACTION = 0.20  # rotate oldest 20% when cap is hit

_ID_RE = re.compile(r"^e_(\d+)$")


def _get_max_events() -> int:
    """Read episodic_max_events from config.json (falls back to default)."""
    try:
        cfg = get_path("config.json")
        if os.path.exists(cfg):
            with open(cfg, encoding="utf-8") as f:
                return int(json.load(f).get("episodic_max_events", _MAX_EVENTS_DEFAULT))
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return _MAX_EVENTS_DEFAULT


def _archive_path() -> str:
    return _file_path().replace("episodic.json", "episodic_archive.json")


def _rotate_if_needed(data: list) -> list:
    """If data exceeds the cap, archive oldest entries and return trimmed list."""
    max_events = _get_max_events()
    if len(data) < max_events:
        return data
    archive_count = max(1, int(len(data) * _ARCHIVE_FRACTION))
    to_archive = data[:archive_count]
    trimmed = data[archive_count:]
    try:
        apath = _archive_path()
        existing: list = []
        if os.path.exists(apath):
            with open(apath, "rb") as f:
                existing = json.loads(f.read())
        with open(apath, "wb") as f:
            f.write(json.dumps(existing + to_archive, indent=2).encode())
    except OSError:
        pass  # archive write failure is non-fatal; rotation still proceeds
    return trimmed


# ── BM25 module-level cache ───────────────────────────────────────────────────
# event IDs (in _BM25_INDEX's row order) for the live-store corpus; cleared on _save()
_BM25_CORPUS: list[str] | None = None
_BM25_INDEX: object | None = None  # BM25Okapi instance, or None when corpus empty
_BM25_LOCK = threading.Lock()


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
    from core.security import get_storage_config  # pylint: disable=import-outside-toplevel
    encrypt, project_id = get_storage_config()
    if encrypt:
        from core.security.encryption import get_or_create_key, decrypt_bytes  # pylint: disable=import-outside-toplevel
        try:
            raw = decrypt_bytes(raw, get_or_create_key(project_id))
        except Exception:  # InvalidToken — file predates encryption; migrate on next save
            pass
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    _warn_on_duplicate_ids(data)
    return data


def _warn_on_duplicate_ids(data: list) -> None:
    """Defensive check: log a warning if the store already contains duplicate IDs."""
    counts = Counter(e["id"] for e in data if "id" in e)
    dupes = sorted(eid for eid, n in counts.items() if n > 1)
    if dupes:
        logger.warning(
            "episodic store has %d duplicate id(s), showing up to 10: %s",
            len(dupes), dupes[:10],
        )


def _max_id_num(entries: list) -> int:
    """Highest numeric suffix among e_<N> IDs in entries, or -1 if none/malformed."""
    best = -1
    for entry in entries:
        match = _ID_RE.match(str(entry.get("id", "")))
        if match:
            best = max(best, int(match.group(1)))
    return best


def _next_event_id(data: list) -> str:
    """
    Compute a store-lifetime-unique event ID: one past the highest e_<N> seen
    across live entries and the archive file, so post-rotation IDs never
    collide with a surviving (or archived) entry's ID.
    """
    max_num = _max_id_num(data)
    apath = _archive_path()
    if os.path.exists(apath):
        try:
            with open(apath, "rb") as f:
                archive = json.loads(f.read())
            max_num = max(max_num, _max_id_num(archive))
        except (OSError, json.JSONDecodeError):
            pass
    return f"e_{max_num + 1}"


def _save(data: list) -> None:
    global _BM25_CORPUS, _BM25_INDEX  # pylint: disable=global-statement
    from core.security import get_storage_config  # pylint: disable=import-outside-toplevel
    encrypt, project_id = get_storage_config()
    content = json.dumps(data, indent=2).encode()
    if encrypt:
        from core.security.encryption import get_or_create_key, encrypt_bytes  # pylint: disable=import-outside-toplevel
        content = encrypt_bytes(content, get_or_create_key(project_id))
    path = _file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    # Invalidate BM25 cache so the next search reflects the updated corpus
    with _BM25_LOCK:
        _BM25_CORPUS = None
        _BM25_INDEX = None


def _build_bm25(data: list):
    """Build a fresh (uncached) BM25 index over `data`. Returns (index, event_ids)."""
    from rank_bm25 import BM25Plus  # pylint: disable=import-outside-toplevel
    corpus: list[list[str]] = []
    event_ids: list[str] = []
    for entry in data:
        text = entry.get("event", "") + " " + json.dumps(entry.get("metadata", {}))
        corpus.append(_tokenize(text))
        event_ids.append(entry["id"])

    if not corpus:
        return None, []
    return BM25Plus(corpus), event_ids


def _get_bm25(data: list):
    """Return (BM25Okapi instance, event_id_list), building from cache if available.

    Caches only the live-store index — callers that merge in archived entries
    (search_episodes(include_archived=True)) must use _build_bm25() directly so
    an archive-inflated corpus never gets stored as the live cache.
    """
    global _BM25_CORPUS, _BM25_INDEX  # pylint: disable=global-statement
    with _BM25_LOCK:
        if _BM25_INDEX is not None and _BM25_CORPUS is not None:
            return _BM25_INDEX, _BM25_CORPUS

        index, event_ids = _build_bm25(data)
        if index is None:
            return None, []

        _BM25_INDEX = index
        _BM25_CORPUS = event_ids
        return _BM25_INDEX, event_ids


def _load_archive() -> list:
    apath = _archive_path()
    if not os.path.exists(apath):
        return []
    try:
        with open(apath, "rb") as f:
            return json.loads(f.read())
    except (OSError, json.JSONDecodeError):
        return []


def log_event(event: str, metadata: dict = None) -> None:
    """
    Append an event (with optional metadata) to the episodic memory store.
    Rotates oldest entries to an archive file when episodic_max_events is exceeded.
    """
    data = _load()
    data = _rotate_if_needed(data)
    entry = {
        "id": _next_event_id(data),
        "event": event,
        "metadata": metadata or {},
        "time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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


def _vec_cache_paths() -> tuple[str, str]:
    return get_path("memory/episodic_vecs.npy"), get_path("memory/episodic_vecs_ids.json")


def _load_vec_cache():
    """Return (ids, vecs) for the persisted embedding cache, or ([], None) if
    missing/corrupt/mismatched — regenerable, so any failure just means a cold cache."""
    vec_path, ids_path = _vec_cache_paths()
    if not (os.path.exists(vec_path) and os.path.exists(ids_path)):
        return [], None
    try:
        import numpy as np  # pylint: disable=import-outside-toplevel
        with open(ids_path, encoding="utf-8") as f:
            ids = json.load(f)
        vecs = np.load(vec_path)
        if len(ids) != vecs.shape[0]:
            return [], None
        return ids, vecs
    except Exception:  # pylint: disable=broad-except
        return [], None


def _save_vec_cache(ids: list, vecs) -> None:
    try:
        import numpy as np  # pylint: disable=import-outside-toplevel
        vec_path, ids_path = _vec_cache_paths()
        np.save(vec_path, vecs.astype("float32"))
        with open(ids_path, "w", encoding="utf-8") as f:
            json.dump(ids, f)
    except OSError:
        pass  # cache write failure is non-fatal — regenerable from source entries


def _semantic_episode_search(data: list, query: str, limit: int) -> list:
    """Vector fallback for search_episodes when BM25 returns no results.

    Entry embeddings are cached by event ID at .cognirepo/memory/episodic_vecs.npy
    (+ id-list sidecar) — entry text is immutable once logged (only the `stale`
    flag mutates), so a cache hit by ID is always valid; no invalidation needed.
    Only the query itself, and any entry not yet in the cache, get encoded.
    """
    try:
        import numpy as np  # pylint: disable=import-outside-toplevel
        from data.memory.embeddings import encode_with_timeout  # pylint: disable=import-outside-toplevel
        q_vec = encode_with_timeout(query)
        q_norm = np.linalg.norm(q_vec)
        if q_norm == 0:
            return []

        cached_ids, cached_vecs = _load_vec_cache()
        cache_index = {eid: i for i, eid in enumerate(cached_ids)}
        new_ids: list[str] = []
        new_vecs: list = []

        scored = []
        for entry in data:
            text = entry.get("event", "") or str(entry.get("metadata", ""))
            if not text:
                continue
            eid = entry.get("id")
            try:
                if eid is not None and eid in cache_index:
                    e_vec = cached_vecs[cache_index[eid]]
                else:
                    e_vec = encode_with_timeout(text[:512])
                    if eid is not None:
                        new_ids.append(eid)
                        new_vecs.append(e_vec)
                e_norm = np.linalg.norm(e_vec)
                if e_norm == 0:
                    continue
                sim = float(np.dot(q_vec, e_vec) / (q_norm * e_norm))
                if sim > 0.3:
                    scored.append((sim, entry))
            except Exception:  # pylint: disable=broad-except
                continue

        if new_ids:
            if cached_vecs is not None and len(cached_ids):
                merged_ids = cached_ids + new_ids
                merged_vecs = np.vstack([cached_vecs, np.array(new_vecs, dtype="float32")])
            else:
                merged_ids = new_ids
                merged_vecs = np.array(new_vecs, dtype="float32")
            _save_vec_cache(merged_ids, merged_vecs)

        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:limit]]
    except Exception:  # pylint: disable=broad-except
        return []


def search_episodes(query: str, limit: int = 10, include_archived: bool = False) -> list:
    """
    Search episodic events. BM25 (keyword) first; vector-similarity fallback
    when BM25 returns zero results (handles synonym and paraphrase mismatches).

    include_archived: also search events rotated out to episodic_archive.json
    (default False — live store only). Archived hits are tagged {"archived": True}.
    """
    data = _load()
    archived_ids: set = set()
    if include_archived:
        archive = _load_archive()
        archived_ids = {e["id"] for e in archive if "id" in e}
        data = archive + data

    if not data:
        return []

    tokens = _tokenize(query)
    if not tokens:
        return []

    bm25, event_ids = _build_bm25(data) if include_archived else _get_bm25(data)
    if bm25 is None:
        return []

    scores = bm25.get_scores(tokens)
    ranked = sorted(
        ((score, eid) for score, eid in zip(scores, event_ids) if score > 0),
        key=lambda x: x[0],
        reverse=True,
    )

    id_to_entry = {e["id"]: e for e in data}
    results = [id_to_entry[eid] for _, eid in ranked[:limit] if eid in id_to_entry]

    if not results:
        results = _semantic_episode_search(data, query, limit)

    if archived_ids:
        for r in results:
            if r.get("id") in archived_ids:
                r["archived"] = True

    return results


class EpisodicMemory:  # pylint: disable=missing-function-docstring
    """Class interface over the module-level episodic memory functions."""

    def log_event(self, event: str, metadata: dict = None) -> None:
        log_event(event, metadata)

    def get_history(self, limit: int = 100) -> list:
        return get_history(limit)

    def search_episodes(self, query: str, limit: int = 10, include_archived: bool = False) -> list:
        return search_episodes(query, limit, include_archived)

    def mark_stale(self, file_path: str) -> int:
        return mark_stale(file_path)


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
