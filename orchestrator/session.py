"""
orchestrator/session.py — conversation session management.

Sessions persist conversation history across CLI invocations so that
follow-up queries can reference previous answers.

Storage layout
--------------
.cognirepo/sessions/<uuid>.json   — individual session files
.cognirepo/sessions/current.json  — pointer to the most recent session

Session schema
--------------
{
  "session_id": "<uuid4>",
  "messages":   [{"role": "user"|"assistant", "content": "..."}],
  "created_at": "<ISO 8601>",
  "model":      "<model id or empty string>"
}

History cap
-----------
Each exchange is one user message + one assistant message (2 messages).
When the cap (default: 10 exchanges = 20 messages) is exceeded, the
oldest exchange is dropped so the context window stays manageable.
The cap can be overridden in ``.cognirepo/config.json``:

.. code-block:: json

    {"session": {"max_exchanges": 20}}
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

_SESSIONS_DIR = Path(".cognirepo/sessions")
_CURRENT_PTR = _SESSIONS_DIR / "current.json"
DEFAULT_MAX_EXCHANGES = 10


# ── public API ────────────────────────────────────────────────────────────────

def create_session(model: str = "") -> dict:
    """Create a new empty session, save it, and mark it as the current session."""
    os.makedirs(_SESSIONS_DIR, exist_ok=True)
    session: dict = {
        "session_id": str(uuid.uuid4()),
        "messages": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
    }
    _save_session(session)
    _set_current(session["session_id"])
    return session


def load_session(session_id: str) -> dict | None:
    """Load a session by exact ID.  Returns None if not found or unreadable."""
    path = _SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def load_current_session() -> dict | None:
    """Load the session pointed to by current.json.  Returns None if none exists."""
    try:
        with open(_CURRENT_PTR, encoding="utf-8") as f:
            ptr = json.load(f)
        return load_session(ptr.get("session_id", ""))
    except (OSError, json.JSONDecodeError):
        return None


def find_session(id_or_prefix: str) -> dict | None:
    """
    Find a session by full ID or a unique ID prefix (≥4 chars).

    Returns None if not found or if the prefix matches more than one session.
    """
    # Try exact match first (fastest path)
    exact = load_session(id_or_prefix)
    if exact:
        return exact

    # Prefix search
    all_sessions = list_sessions(limit=0)  # 0 = no limit
    matches = [s for s in all_sessions if s["session_id"].startswith(id_or_prefix)]
    if len(matches) == 1:
        return matches[0]
    return None


def append_exchange(
    session: dict,
    user_msg: str,
    assistant_msg: str,
    max_exchanges: int = DEFAULT_MAX_EXCHANGES,
) -> dict:
    """
    Append a user/assistant exchange to *session* and enforce the history cap.

    When the number of stored exchanges exceeds *max_exchanges*, the oldest
    exchange (one user + one assistant message) is dropped.

    The updated session is saved to disk automatically.
    """
    session["messages"].append({"role": "user", "content": user_msg})
    session["messages"].append({"role": "assistant", "content": assistant_msg})

    # Enforce cap: each exchange = 2 messages
    max_msgs = max_exchanges * 2
    excess = len(session["messages"]) - max_msgs
    if excess > 0:
        # Drop oldest exchanges in pairs (always keep messages balanced)
        drop = ((excess + 1) // 2) * 2
        session["messages"] = session["messages"][drop:]

    _save_session(session)
    _set_current(session["session_id"])
    return session


def list_sessions(limit: int = 20) -> list[dict]:
    """
    Return sessions sorted newest-first.

    Parameters
    ----------
    limit : Maximum sessions to return.  0 or negative means no limit.
    """
    if not _SESSIONS_DIR.exists():
        return []

    sessions: list[dict] = []
    for path in _SESSIONS_DIR.glob("*.json"):
        if path.name == "current.json":
            continue
        try:
            with open(path, encoding="utf-8") as f:
                sessions.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            continue

    sessions.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    if limit and limit > 0:
        sessions = sessions[:limit]
    return sessions


def current_session_id() -> str | None:
    """Return the ID of the current session, or None."""
    try:
        with open(_CURRENT_PTR, encoding="utf-8") as f:
            return json.load(f).get("session_id")
    except (OSError, json.JSONDecodeError):
        return None


def load_max_exchanges() -> int:
    """Read max_exchanges from config.json, falling back to DEFAULT_MAX_EXCHANGES."""
    try:
        with open(".cognirepo/config.json", encoding="utf-8") as f:
            cfg = json.load(f)
        return int(cfg.get("session", {}).get("max_exchanges", DEFAULT_MAX_EXCHANGES))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return DEFAULT_MAX_EXCHANGES


# ── internal helpers ──────────────────────────────────────────────────────────

def _save_session(session: dict) -> None:
    os.makedirs(_SESSIONS_DIR, exist_ok=True)
    path = _SESSIONS_DIR / f"{session['session_id']}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(session, f, indent=2, ensure_ascii=False)


def _set_current(session_id: str) -> None:
    os.makedirs(_SESSIONS_DIR, exist_ok=True)
    with open(_CURRENT_PTR, "w", encoding="utf-8") as f:
        json.dump({"session_id": session_id}, f)
