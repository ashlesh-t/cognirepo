"""
Functions for logging and managing episodic memory.
"""
import json
import os
from datetime import datetime


FILE = ".cognirepo/memory/episodic.json"


def _load() -> list:
    if not os.path.exists(FILE):
        os.makedirs(os.path.dirname(FILE), exist_ok=True)
        return []
    with open(FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: list) -> None:
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


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
