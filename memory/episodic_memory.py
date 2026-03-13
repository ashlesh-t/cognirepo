"""
Functions for logging and managing episodic memory.
"""
import json
import os
from datetime import datetime


FILE = ".cognirepo/memory/episodic.json"


def log_event(event):
    """
    Append an event to the episodic memory store.
    """
    if not os.path.exists(FILE):
        with open(FILE, "w", encoding="utf-8") as f:
            json.dump([], f)

    with open(FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    data.append({
        "event": event,
        "time": str(datetime.now())
    })

    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)
