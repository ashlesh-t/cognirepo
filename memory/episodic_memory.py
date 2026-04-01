# pylint: disable=duplicate-code
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Functions for logging and managing episodic memory.
"""
import json
import os
from datetime import datetime


from config.paths import get_path

def _file_path() -> str:
    return get_path("memory/episodic.json")


def _index_file() -> str:
    return get_path("memory/episodic_index.json")


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
    _build_index(data)


def _build_index(data: list) -> None:
    """Build a simple keyword → [event_ids] index for fast search."""
    index = {}
    for entry in data:
        eid = entry["id"]
        # Index words from event text and metadata
        text = (entry.get("event", "") + " " + json.dumps(entry.get("metadata", {}))).lower()
        import re
        words = set(re.findall(r"\w+", text))
        for w in words:
            if len(w) < 3:
                continue
            index.setdefault(w, [])
            if eid not in index[w]:
                index[w].append(eid)
    
    with open(_index_file(), "w", encoding="utf-8") as f:
        json.dump(index, f)


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
    Search episodic events using the keyword index.
    """
    if not os.path.exists(_index_file()):
        # Fallback to full scan if index missing
        query_lower = query.lower()
        data = _load()
        matches = []
        for entry in reversed(data):
            if query_lower in entry.get("event", "").lower() or \
               query_lower in json.dumps(entry.get("metadata", {})).lower():
                matches.append(entry)
                if len(matches) >= limit:
                    break
        return matches

    with open(_index_file(), "r", encoding="utf-8") as f:
        index = json.load(f)
    
    import re
    query_words = re.findall(r"\w+", query.lower())
    if not query_words:
        return []
    
    # Intersection of matches for all words
    match_ids = None
    for w in query_words:
        hits = set(index.get(w, []))
        if match_ids is None:
            match_ids = hits
        else:
            match_ids &= hits
    
    if not match_ids:
        return []
    
    # Load data and filter
    data = _load()
    id_to_entry = {e["id"]: e for e in data}
    results = [id_to_entry[eid] for eid in sorted(match_ids, key=lambda x: int(x.split("_")[1]), reverse=True)]
    return results[:limit]
