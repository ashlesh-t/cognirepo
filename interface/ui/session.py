# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Session file for a running UI server: token + port + pid, 0600, under the global dir.

Lives under ``get_global_path("ui/")`` (honours COGNIREPO_GLOBAL_DIR, so tests never touch the
real home). The token is a per-session secret: never log it, never print it unless the browser
could not be opened.
"""
from __future__ import annotations

import json
import os
import socket
from typing import Any


def session_path() -> str:
    from core.config.paths import get_global_path  # pylint: disable=import-outside-toplevel
    return get_global_path("ui/session.json")


def write_session(token: str, host: str, port: int, pid: int, repo_root: str) -> None:
    path = session_path()
    tmp = f"{path}.{pid}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"token": token, "host": host, "port": port, "pid": pid, "repo_root": repo_root}, f)
    os.replace(tmp, path)


def read_session() -> dict[str, Any] | None:
    try:
        with open(session_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    ok = isinstance(data, dict) and isinstance(data.get("token"), str) and isinstance(data.get("port"), int)
    return data if ok else None


def clear_session(only_pid: int | None = None) -> None:
    """Remove the session file (when ``only_pid`` is given, only if it is that server's)."""
    sess = read_session()
    if only_pid is not None and (sess is None or sess.get("pid") != only_pid):
        return
    try:
        os.unlink(session_path())
    except OSError:
        pass


def is_listening(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    """Cross-platform liveness probe (no os.kill(pid, 0), which is unsafe on Windows)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
