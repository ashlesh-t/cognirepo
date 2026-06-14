# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
cli/cli_config.py — user-level CLI configuration.

Reads ``~/.cognirepo/cli_config.toml``.  If the file is missing, it is created
with sensible defaults on first access.  If the file is corrupt (invalid TOML),
a warning is logged and defaults are used — the REPL never crashes over config.

Schema (all keys are optional in the file; defaults shown below):

    [ui]
    theme    = "auto"   # "auto" | "dark" | "light" | "plain"
    multiline = false   # accept multi-line input (prompt_toolkit only)

    [model]
    prefer   = ""       # preferred model override (empty = classifier decides)
    force_tier = ""     # force tier: "QUICK"|"STANDARD"|"COMPLEX"|"EXPERT"|""

    [session]
    persist        = true   # auto-save session history to disk
    max_exchanges  = 20     # rolling history cap (user+assistant pairs kept)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_GLOBAL_DIR = Path(os.environ.get("COGNIREPO_GLOBAL_DIR", Path.home() / ".cognirepo"))
_CONFIG_PATH = _GLOBAL_DIR / "cli_config.toml"

_DEFAULT_TOML = """\
[ui]
theme = "auto"
multiline = false

[model]
prefer = ""
force_tier = ""

[session]
persist = true
max_exchanges = 20
"""

_VALID_THEMES = {"auto", "dark", "light", "plain"}
_VALID_TIERS = {"", "QUICK", "STANDARD", "COMPLEX", "EXPERT"}


@dataclass
class UIConfig:
    theme: str = "auto"
    multiline: bool = False


@dataclass
class ModelConfig:
    prefer: str = ""
    force_tier: str = ""


@dataclass
class SessionConfig:
    persist: bool = True
    max_exchanges: int = 20


@dataclass
class CLIConfig:
    ui: UIConfig = field(default_factory=UIConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    session: SessionConfig = field(default_factory=SessionConfig)


def _read_toml(path: Path) -> dict[str, Any]:
    """Read a TOML file; return {} on any error."""
    try:
        import tomllib  # Python 3.11+  # pylint: disable=import-outside-toplevel
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]  # pylint: disable=import-outside-toplevel
        except ImportError:
            logger.warning("cli_config: tomllib unavailable — using defaults")
            return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("cli_config: failed to parse %s (%s) — using defaults", path, exc)
        return {}


def _write_defaults(path: Path) -> None:
    """Create the config file with defaults if it doesn't exist."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(_DEFAULT_TOML, encoding="utf-8")
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("cli_config: could not write defaults to %s: %s", path, exc)


def load_cli_config(path: Path | None = None) -> CLIConfig:
    """
    Load and validate CLI config.  Creates ``~/.cognirepo/cli_config.toml``
    on first run.  Never raises — falls back to CLIConfig() on any error.
    """
    target = path or _CONFIG_PATH
    _write_defaults(target)
    raw = _read_toml(target)

    # ── ui ────────────────────────────────────────────────────────────────────
    ui_raw = raw.get("ui", {}) if isinstance(raw.get("ui"), dict) else {}
    theme = str(ui_raw.get("theme", "auto"))
    if theme not in _VALID_THEMES:
        logger.warning("cli_config: unknown theme %r — using 'auto'", theme)
        theme = "auto"
    ui = UIConfig(
        theme=theme,
        multiline=bool(ui_raw.get("multiline", False)),
    )

    # ── model ─────────────────────────────────────────────────────────────────
    model_raw = raw.get("model", {}) if isinstance(raw.get("model"), dict) else {}
    force_tier = str(model_raw.get("force_tier", "")).upper()
    if force_tier not in _VALID_TIERS:
        logger.warning("cli_config: unknown force_tier %r — ignoring", force_tier)
        force_tier = ""
    model_cfg = ModelConfig(
        prefer=str(model_raw.get("prefer", "")),
        force_tier=force_tier,
    )

    # ── session ───────────────────────────────────────────────────────────────
    sess_raw = raw.get("session", {}) if isinstance(raw.get("session"), dict) else {}
    try:
        max_ex = int(sess_raw.get("max_exchanges", 20))
        if max_ex < 1:
            max_ex = 20
    except (TypeError, ValueError):
        max_ex = 20
    sess = SessionConfig(
        persist=bool(sess_raw.get("persist", True)),
        max_exchanges=max_ex,
    )

    return CLIConfig(ui=ui, model=model_cfg, session=sess)
