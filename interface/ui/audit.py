# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Local audit log for control actions: JSON lines, 0600, size-rotated, never holds secrets."""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

_SECRET_KEYS = frozenset({"token", "authorization", "cookie", "set-cookie", "password"})
_MAX_BYTES = 1_048_576


class AuditLog:
    """Append-only JSONL log. One backup generation (``<path>.1``) when it exceeds 1 MiB."""

    def __init__(self, path: str, max_bytes: int = _MAX_BYTES) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self._lock = threading.Lock()

    def log(self, action: str, **fields: Any) -> None:
        clean = {k: v for k, v in fields.items() if k.lower() not in _SECRET_KEYS}
        record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "action": action, **clean}
        line = (json.dumps(record, default=str) + "\n").encode("utf-8")
        with self._lock:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            self._rotate_if_needed(len(line))
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, line)
            finally:
                os.close(fd)

    def _rotate_if_needed(self, incoming: int) -> None:
        try:
            if os.path.getsize(self.path) + incoming > self.max_bytes:
                os.replace(self.path, self.path + ".1")
        except OSError:
            pass

    def tail(self, n: int = 100) -> list[dict]:
        """Last ``n`` records (for the console's audit view). Unreadable lines are skipped."""
        try:
            with open(self.path, encoding="utf-8") as f:
                lines = f.readlines()[-n:]
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
