"""
Shared context store — any model can push/pull partial reasoning state
for a session.  Persists under .cognirepo/sessions/<context_id>.json.

Design
------
Each session is a flat JSON file:
  {
    "context_id": "q_abc123",
    "entries": { "reasoning_step_1": "...", "sub_result": "..." },
    "last_updated": 1712345678901
  }

Thread-safe via a per-session RLock (gRPC server runs in a thread pool).
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

SESSIONS_DIR = ".cognirepo/sessions"


class ContextStore:
    def __init__(self, sessions_dir: str = SESSIONS_DIR) -> None:
        self._dir = sessions_dir
        os.makedirs(self._dir, exist_ok=True)
        self._locks: dict[str, threading.RLock] = {}
        self._meta_lock = threading.Lock()

    # ── public API ────────────────────────────────────────────────────────────

    def push(self, context_id: str, key: str, value: str) -> str:
        """
        Write a key-value pair into a session.  Returns an opaque version token
        (unix-millis string) for optimistic concurrency checks by the caller.
        """
        lock = self._get_lock(context_id)
        with lock:
            data = self._load(context_id)
            data["entries"][key] = value
            ts = int(time.time() * 1000)
            data["last_updated"] = ts
            self._save(context_id, data)
        return str(ts)

    def get(self, context_id: str, key: str = "") -> dict[str, str]:
        """
        Return entries for a session.  If key is given, returns {key: value}
        (empty dict if key absent).  key="" returns all entries.
        """
        lock = self._get_lock(context_id)
        with lock:
            data = self._load(context_id)
        entries = data.get("entries", {})
        if key:
            return {key: entries[key]} if key in entries else {}
        return dict(entries)

    def last_updated(self, context_id: str) -> int:
        lock = self._get_lock(context_id)
        with lock:
            data = self._load(context_id)
        return data.get("last_updated", 0)

    def list_sessions(self, limit: int = 0) -> list[str]:
        """Return context_ids sorted by last_updated descending."""
        sessions = []
        for fname in Path(self._dir).glob("*.json"):
            try:
                with open(fname, encoding="utf-8") as f:
                    d = json.load(f)
                sessions.append((d.get("last_updated", 0), fname.stem))
            except (json.JSONDecodeError, OSError):
                continue
        sessions.sort(reverse=True)
        ids = [s[1] for s in sessions]
        return ids[:limit] if limit > 0 else ids

    # ── internal ──────────────────────────────────────────────────────────────

    def _path(self, context_id: str) -> str:
        # Sanitise: only allow alphanumeric, dash, underscore
        safe = "".join(c for c in context_id if c.isalnum() or c in "-_")
        return os.path.join(self._dir, f"{safe}.json")

    def _load(self, context_id: str) -> dict:
        path = self._path(context_id)
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {"context_id": context_id, "entries": {}, "last_updated": 0}

    def _save(self, context_id: str, data: dict) -> None:
        path = self._path(context_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _get_lock(self, context_id: str) -> threading.RLock:
        with self._meta_lock:
            if context_id not in self._locks:
                self._locks[context_id] = threading.RLock()
            return self._locks[context_id]


# Module-level singleton — shared by server and any in-process callers.
_store: ContextStore | None = None


def get_store() -> ContextStore:
    global _store  # pylint: disable=global-statement
    if _store is None:
        _store = ContextStore()
    return _store
