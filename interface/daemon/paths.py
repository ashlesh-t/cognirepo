# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Where the daemon's sockets and state live, and the settings that control it.

The run directory is ``$COGNIREPO_RUN_DIR``, else ``$XDG_RUNTIME_DIR/cognirepo``, else ``<global dir>/run``. It is
created ``0700`` and refused if it belongs to someone else or is group/world accessible, so the sockets in it are
reachable only by this user. ``AF_UNIX`` paths are limited to ~104 bytes; a too-long run directory is reported
(``RunDirError``) rather than failing obscurely later.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from typing import Any

SOCKET_PATH_MAX = 100          # sun_path is 104 (macOS) / 108 (Linux) bytes including the NUL
SUPPORTED = os.name == "posix" and hasattr(__import__("socket"), "AF_UNIX")

_DEFAULTS = {"enabled": False, "idle_exit_secs": 900, "worker_idle_secs": 600, "max_workers": 4, "worker_concurrency": 2,
             "connect_timeout_secs": 3.0, "request_timeout_secs": 120.0, "spawn_timeout_secs": 60.0}


class RunDirError(RuntimeError):
    pass


def _global_config() -> dict[str, Any]:
    try:
        from core.config.paths import get_global_dir  # pylint: disable=import-outside-toplevel
        with open(os.path.join(get_global_dir(), "config.json"), encoding="utf-8") as fh:
            section = json.load(fh).get("daemon")
        return section if isinstance(section, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def setting(name: str) -> Any:
    """``daemon.<name>``: ``COGNIREPO_DAEMON_<NAME>`` env wins over the ``daemon`` section of ``<global>/config.json``."""
    default = _DEFAULTS[name]
    raw = os.environ.get(f"COGNIREPO_DAEMON_{name.upper()}")
    if raw is None and name == "enabled":
        raw = os.environ.get("COGNIREPO_DAEMON")
    if raw is None:
        raw = _global_config().get(name, default)
    try:
        if isinstance(default, bool):
            return str(raw).strip().lower() in ("1", "true", "yes", "on")
        return type(default)(raw)
    except (TypeError, ValueError):
        return default


def enabled() -> bool:
    return SUPPORTED and bool(setting("enabled"))


def run_dir(create: bool = True) -> str:
    base = os.environ.get("COGNIREPO_RUN_DIR")
    if not base:
        xdg = os.environ.get("XDG_RUNTIME_DIR")
        if xdg and os.path.isdir(xdg):
            base = os.path.join(xdg, "cognirepo")
        else:
            from core.config.paths import get_global_dir  # pylint: disable=import-outside-toplevel
            base = os.path.join(get_global_dir(), "run")
    base = os.path.abspath(base)
    if create:
        os.makedirs(base, mode=0o700, exist_ok=True)
        check_private(base)
    return base


def check_private(path: str) -> None:
    """Raise ``RunDirError`` unless ``path`` is a directory owned by us that nobody else can enter."""
    st = os.stat(path)
    if not stat.S_ISDIR(st.st_mode):
        raise RunDirError(f"{path} is not a directory")
    if hasattr(os, "getuid") and st.st_uid != os.getuid():
        raise RunDirError(f"{path} is owned by another user")
    if st.st_mode & 0o077:
        try:
            os.chmod(path, 0o700)
        except OSError as exc:
            raise RunDirError(f"{path} is accessible to other users and cannot be tightened: {exc}") from exc


def supervisor_socket() -> str:
    return _checked(os.path.join(run_dir(), "daemon.sock"))


def supervisor_lock() -> str:
    return os.path.join(run_dir(), "daemon.lock")


def start_lock() -> str:
    return os.path.join(run_dir(), "start.lock")


def state_file() -> str:
    return os.path.join(run_dir(), "daemon.json")


def log_file() -> str:
    return os.path.join(run_dir(), "daemon.log")


def worker_key(repo_root: str) -> str:
    return hashlib.sha256(os.path.abspath(repo_root).encode("utf-8")).hexdigest()[:12]


def worker_socket(repo_root: str) -> str:
    return _checked(os.path.join(run_dir(), f"w-{worker_key(repo_root)}.sock"))


def _checked(path: str) -> str:
    if len(path.encode("utf-8")) > SOCKET_PATH_MAX:
        raise RunDirError(f"socket path too long for AF_UNIX ({len(path)} bytes): {path}; "
                          "set COGNIREPO_RUN_DIR to a shorter directory")
    return path


def python_argv(module: str, *args: str) -> list[str]:
    """argv that runs ``module`` with the interpreter running us (never a bare ``cognirepo`` on PATH)."""
    return [sys.executable, "-m", module, *args]
