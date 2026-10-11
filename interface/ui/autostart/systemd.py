# Copyright (c) 2026 Ashlesh T. — AGPL-3.0 (see LICENSE)
"""Linux: a systemd *user* service, ``~/.config/systemd/user/<name>.service``."""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

from core.config.atomic import atomic_write
from interface.ui.autostart import AutostartError

#: SIGTERM makes the watcher flush its pending edits; give it longer than its own bound (60s default)
STOP_TIMEOUT_SECS = 60


def unit_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"


def unit_path(name: str) -> Path:
    return unit_dir() / f"{name}.service"


def render(name: str, argv: list[str], cwd: str, description: str | None = None) -> str:
    """Unit text. ``Restart=on-failure``: a crash or SIGKILL is revived, a clean SIGTERM
    (``cognirepo list --stop``, ``systemctl stop``) stays stopped. Quoting keeps a path with
    spaces as one argument (systemd honours shell-style quotes in ExecStart)."""
    exec_start = " ".join(shlex.quote(a) for a in argv)
    return f"""\
[Unit]
Description={description or name}
After=network.target

[Service]
Type=simple
ExecStart={exec_start}
Restart=on-failure
RestartSec=10
TimeoutStopSec={STOP_TIMEOUT_SECS}
WorkingDirectory={cwd}

[Install]
WantedBy=default.target
"""


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    exe = shutil.which("systemctl")
    if not exe:
        raise AutostartError("systemctl not found — is this a systemd system?")
    return subprocess.run([exe, "--user", *args], capture_output=True, text=True, check=False)


def _must(*args: str) -> None:
    res = _systemctl(*args)
    if res.returncode != 0:
        raise AutostartError(f"systemctl --user {' '.join(args)} failed: {(res.stderr or res.stdout).strip()}")


def install(name: str, argv: list[str], cwd: str, description: str | None = None) -> Path:
    """Write the unit, enable it and start it now. Re-running rewrites and restarts: idempotent."""
    path = unit_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(str(path), render(name, argv, cwd, description))
    _must("daemon-reload")
    _must("enable", "--now", f"{name}.service")
    return path


def uninstall(name: str) -> bool:
    """Stop, disable and delete the unit. False if it was not installed. Never raises for 'not loaded'."""
    path = unit_path(name)
    if not path.exists():
        return False
    _systemctl("disable", "--now", f"{name}.service")   # best effort: it may already be stopped
    path.unlink(missing_ok=True)
    _systemctl("daemon-reload")
    return True


def is_installed(name: str) -> bool:
    return unit_path(name).exists()
