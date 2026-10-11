# Copyright (c) 2026 Ashlesh T. — AGPL-3.0 (see LICENSE)
"""macOS: a launchd *user agent*, ``~/Library/LaunchAgents/<label>.plist``."""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from pathlib import Path

from core.config.atomic import atomic_write
from interface.ui.autostart import AutostartError


def label(name: str) -> str:
    return f"io.cognirepo.{name}"


def plist_path(name: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label(name)}.plist"


def render(name: str, argv: list[str], cwd: str) -> bytes:
    """``KeepAlive.SuccessfulExit=false``: restarted after a crash or kill, left alone after a clean exit."""
    log = Path.home() / "Library" / "Logs" / f"{label(name)}.log"
    return plistlib.dumps({
        "Label": label(name),
        "ProgramArguments": list(argv),
        "WorkingDirectory": cwd,
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 10,
        "ExitTimeOut": 60,
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
    })


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    exe = shutil.which("launchctl")
    if not exe:
        raise AutostartError("launchctl not found")
    return subprocess.run([exe, *args], capture_output=True, text=True, check=False)


def _domain() -> str:
    return f"gui/{os.getuid()}"


def install(name: str, argv: list[str], cwd: str, description: str | None = None) -> Path:  # pylint: disable=unused-argument
    path = plist_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    Path.home().joinpath("Library", "Logs").mkdir(parents=True, exist_ok=True)
    _launchctl("bootout", f"{_domain()}/{label(name)}")      # replace a previous load, if any
    atomic_write(str(path), render(name, argv, cwd))
    res = _launchctl("bootstrap", _domain(), str(path))
    if res.returncode != 0:
        raise AutostartError(f"launchctl bootstrap failed: {(res.stderr or res.stdout).strip()}")
    return path


def uninstall(name: str) -> bool:
    path = plist_path(name)
    if not path.exists():
        return False
    _launchctl("bootout", f"{_domain()}/{label(name)}")
    path.unlink(missing_ok=True)
    return True


def is_installed(name: str) -> bool:
    return plist_path(name).exists()
