# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Global user memory — stored in ~/.cognirepo/user/

Tracks user behaviour patterns and preferences that persist across all projects.
Project-specific memories stay in .cognirepo/ as before.

Storage layout under ~/.cognirepo/user/:
  behaviour.json   — key/value preferences set explicitly by the user
  patterns.json    — auto-tracked behaviour counts (query types, tools used, etc.)
"""
import json
import os
from datetime import datetime

from config.paths import get_global_path

_BEHAVIOUR_FILE = "user/behaviour.json"
_PATTERNS_FILE  = "user/patterns.json"


# ── internal helpers ──────────────────────────────────────────────────────────

def _load(rel_path: str) -> dict:
    path = get_global_path(rel_path)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(rel_path: str, data: dict) -> None:
    path = get_global_path(rel_path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ── user preferences (explicit key/value settings) ───────────────────────────

def set_preference(key: str, value) -> None:
    """Persist a user preference globally (e.g. default_model_tier, encrypt_default)."""
    prefs = _load(_BEHAVIOUR_FILE)
    prefs[key] = {"value": value, "updated": datetime.utcnow().isoformat() + "Z"}
    _save(_BEHAVIOUR_FILE, prefs)


def get_preference(key: str, default=None):
    """Retrieve a user preference. Returns *default* if not set."""
    prefs = _load(_BEHAVIOUR_FILE)
    entry = prefs.get(key)
    if entry is None:
        return default
    return entry.get("value", default)


def list_preferences() -> dict:
    """Return all stored user preferences as {key: value} (timestamps stripped)."""
    return {k: v.get("value") for k, v in _load(_BEHAVIOUR_FILE).items()}


# ── behaviour pattern tracking (auto-incremented counters) ───────────────────

def record_action(action: str) -> None:
    """
    Increment the counter for *action* in the global behaviour pattern store.

    Typical callers: retrieve_memory (action="retrieve"), store_memory (action="store"),
    index-repo (action="index"), etc.
    """
    patterns = _load(_PATTERNS_FILE)
    entry = patterns.get(action, {"count": 0, "first_seen": datetime.utcnow().isoformat() + "Z"})
    entry["count"] = entry.get("count", 0) + 1
    entry["last_seen"] = datetime.utcnow().isoformat() + "Z"
    patterns[action] = entry
    _save(_PATTERNS_FILE, patterns)


def get_behaviour_summary() -> dict:
    """Return all tracked actions with their counts and timestamps."""
    return _load(_PATTERNS_FILE)
