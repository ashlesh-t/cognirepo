# SPDX-FileCopyrightText: 2026 Ashlesh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/your-username/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

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
    with open(FILE, "rb") as f:
        raw = f.read()
    from security import get_storage_config  # pylint: disable=import-outside-toplevel
    encrypt, project_id = get_storage_config()
    if encrypt:
        from security.encryption import get_or_create_key, decrypt_bytes  # pylint: disable=import-outside-toplevel
        raw = decrypt_bytes(raw, get_or_create_key(project_id))
    return json.loads(raw)


def _save(data: list) -> None:
    from security import get_storage_config  # pylint: disable=import-outside-toplevel
    encrypt, project_id = get_storage_config()
    content = json.dumps(data, indent=2).encode()
    if encrypt:
        from security.encryption import get_or_create_key, encrypt_bytes  # pylint: disable=import-outside-toplevel
        content = encrypt_bytes(content, get_or_create_key(project_id))
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    with open(FILE, "wb") as f:
        f.write(content)


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
