# Copyright (c) 2026 Ashlesh T. — AGPL-3.0 (see LICENSE)
"""Opt-in autostart of a command under the OS service manager (#146).

One entry per ``(name, argv, cwd)``, idempotent, removable. Each backend module exposes the same
three functions — ``install(name, argv, cwd)``, ``uninstall(name)``, ``is_installed(name)`` —
and returns/raises plainly: ``AutostartError`` for anything the caller should show the user.

``unit_name_for_repo`` gives the per-repo name, so the watcher and (later) the control API's
``cognirepo ui`` can share this without clashing.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
from types import ModuleType


class AutostartError(RuntimeError):
    """The service manager is missing, or refused the request."""


def unit_name_for_repo(repo_path: str, prefix: str = "cognirepo-watcher") -> str:
    """``cognirepo-watcher-<dirname>-<8 hex of the abs path>`` — stable, filesystem/launchd safe."""
    abs_repo = os.path.abspath(repo_path)
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", os.path.basename(abs_repo)).strip("-") or "repo"
    return f"{prefix}-{slug[:32]}-{hashlib.sha256(abs_repo.encode()).hexdigest()[:8]}"


def backend() -> ModuleType:
    """The backend module for this OS; ``AutostartError`` where there is none."""
    if sys.platform.startswith("linux"):
        from interface.ui.autostart import systemd as mod  # pylint: disable=import-outside-toplevel
    elif sys.platform == "darwin":
        from interface.ui.autostart import launchd as mod  # pylint: disable=import-outside-toplevel
    elif sys.platform in ("win32", "cygwin"):
        from interface.ui.autostart import schtasks as mod  # pylint: disable=import-outside-toplevel
    else:
        raise AutostartError(f"autostart is not supported on {sys.platform}")
    return mod
