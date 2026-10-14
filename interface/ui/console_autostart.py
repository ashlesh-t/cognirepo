# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Opt-in autostart of the local control server at login (#129).

Policy only. The OS service backends (systemd --user / launchd / Task Scheduler) are the shared,
parameterised ones in ``interface.ui.autostart`` that ``watch --autostart`` (#146) also uses; this
module decides *what* to run: always the SAME fixed command with an explicit ``--host 127.0.0.1``,
so an autostarted server is loopback-only by construction (``--unsafe-bind`` can never end up in a
unit file).
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable, NamedTuple

from core.config.atomic import atomic_json_dump
from interface.ui import autostart as _backends

PROMPT = "Start the console automatically at login? (y/N) "
UNIT_NAME = "cognirepo-ui"


class Result(NamedTuple):
    changed: bool
    detail: str
    ok: bool = True


def build_argv() -> list[str]:
    # The interpreter that ran `--autostart on` is, by definition, one that has `ui`. A bare
    # `cognirepo` found on PATH may be a stale install (e.g. an old pipx copy) that does not.
    argv = [sys.executable, "-m", "interface.cli.main", "ui", "--serve", "--no-open", "--host", "127.0.0.1"]
    assert "--unsafe-bind" not in argv  # nosec B101 — invariant: autostart is loopback-only
    return argv


def enable(repo_root: str) -> Result:
    try:
        path = _backends.backend().install(
            UNIT_NAME, build_argv(), os.path.abspath(repo_root),
            "CogniRepo local control API / Engram console (loopback only)",
        )
    except _backends.AutostartError as exc:
        return Result(False, str(exc), ok=False)
    save_config(autostart=True, autostart_asked=True, repo_root=os.path.abspath(repo_root))
    return Result(True, f"enabled ({path})")


def disable() -> Result:
    try:
        removed = _backends.backend().uninstall(UNIT_NAME)
    except _backends.AutostartError as exc:
        return Result(False, str(exc), ok=False)
    save_config(autostart=False)
    return Result(removed, "autostart removed" if removed else "autostart was not enabled")


# ── first-run prompt state ───────────────────────────────────────────────────

def _config_path() -> str:
    from core.config.paths import get_global_path  # pylint: disable=import-outside-toplevel
    return get_global_path("ui/config.json")


def load_config() -> dict[str, Any]:
    try:
        with open(_config_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_config(**updates: Any) -> None:
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_json_dump(path, {**load_config(), **updates})


def maybe_prompt(repo_root: str, input_fn: Callable[[str], str] = input,
                 is_tty: bool | None = None) -> Result | None:
    """First run only, interactive only, default No. Returns the enable() result if the user said yes."""
    tty = sys.stdin.isatty() if is_tty is None else is_tty
    if not tty or load_config().get("autostart_asked"):
        return None
    try:
        answer = input_fn(PROMPT).strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    save_config(autostart_asked=True)  # never ask twice, whatever the answer
    if answer in ("y", "yes"):
        return enable(repo_root)
    return None
