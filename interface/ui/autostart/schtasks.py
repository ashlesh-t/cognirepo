# Copyright (c) 2026 Ashlesh T. — AGPL-3.0 (see LICENSE)
"""Windows: a Task Scheduler task that starts at logon.

Task Scheduler restarts a failed task via its own settings, which ``schtasks /Create`` cannot set
from the command line; so on Windows this gives *start at logon* and the catch-up reindex covers
the gap if the watcher dies — it does not supervise.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from interface.ui.autostart import AutostartError


def task_name(name: str) -> str:
    return f"CogniRepo\\{name}"


def _schtasks(*args: str) -> subprocess.CompletedProcess:
    exe = shutil.which("schtasks")
    if not exe:
        raise AutostartError("schtasks not found")
    return subprocess.run([exe, *args], capture_output=True, text=True, check=False)


def render(argv: list[str], cwd: str) -> str:
    """The /TR command line: cd to the repo, then run (``cmd /c`` because /TR has no cwd)."""
    return f'cmd /c cd /d "{cwd}" && ' + subprocess.list2cmdline(argv)


def install(name: str, argv: list[str], cwd: str, description: str | None = None) -> Path:  # pylint: disable=unused-argument
    res = _schtasks("/Create", "/F", "/SC", "ONLOGON", "/TN", task_name(name), "/TR", render(argv, cwd))
    if res.returncode != 0:
        raise AutostartError(f"schtasks /Create failed: {(res.stderr or res.stdout).strip()}")
    _schtasks("/Run", "/TN", task_name(name))
    return Path(task_name(name))


def uninstall(name: str) -> bool:
    if not is_installed(name):
        return False
    _schtasks("/End", "/TN", task_name(name))
    res = _schtasks("/Delete", "/F", "/TN", task_name(name))
    if res.returncode != 0:
        raise AutostartError(f"schtasks /Delete failed: {(res.stderr or res.stdout).strip()}")
    return True


def is_installed(name: str) -> bool:
    return _schtasks("/Query", "/TN", task_name(name)).returncode == 0
