# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""Tests for cli/cli_config.py — load, validate, defaults, corrupt file."""
from __future__ import annotations

from pathlib import Path

from cli.cli_config import load_cli_config, CLIConfig, _DEFAULT_TOML


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "cli_config.toml"
    p.write_text(content, encoding="utf-8")
    return p


# ── defaults ──────────────────────────────────────────────────────────────────

def test_missing_file_creates_defaults(tmp_path):
    cfg_path = tmp_path / "cli_config.toml"
    cfg = load_cli_config(cfg_path)
    assert isinstance(cfg, CLIConfig)
    assert cfg_path.exists()  # should have been created
    assert cfg.ui.theme == "auto"
    assert cfg.session.persist is True
    assert cfg.session.max_exchanges == 20


def test_empty_file_uses_defaults(tmp_path):
    p = _write(tmp_path, "")
    cfg = load_cli_config(p)
    assert cfg.ui.theme == "auto"
    assert cfg.model.prefer == ""
    assert cfg.session.max_exchanges == 20


# ── valid config ───────────────────────────────────────────────────────────────

def test_valid_config_loaded_correctly(tmp_path):
    p = _write(tmp_path, """
[ui]
theme = "dark"
multiline = true

[model]
prefer = "claude-opus-4-6"
force_tier = "EXPERT"

[session]
persist = false
max_exchanges = 5
""")
    cfg = load_cli_config(p)
    assert cfg.ui.theme == "dark"
    assert cfg.ui.multiline is True
    assert cfg.model.prefer == "claude-opus-4-6"
    assert cfg.model.force_tier == "EXPERT"
    assert cfg.session.persist is False
    assert cfg.session.max_exchanges == 5


def test_partial_config_fills_defaults(tmp_path):
    p = _write(tmp_path, "[ui]\ntheme = \"light\"\n")
    cfg = load_cli_config(p)
    assert cfg.ui.theme == "light"
    assert cfg.session.persist is True  # default
    assert cfg.model.prefer == ""       # default


# ── validation ────────────────────────────────────────────────────────────────

def test_invalid_theme_falls_back_to_auto(tmp_path):
    p = _write(tmp_path, '[ui]\ntheme = "neon"\n')
    cfg = load_cli_config(p)
    assert cfg.ui.theme == "auto"


def test_invalid_tier_falls_back_to_empty(tmp_path):
    p = _write(tmp_path, '[model]\nforce_tier = "TURBO"\n')
    cfg = load_cli_config(p)
    assert cfg.model.force_tier == ""


def test_max_exchanges_below_one_resets_to_default(tmp_path):
    p = _write(tmp_path, "[session]\nmax_exchanges = 0\n")
    cfg = load_cli_config(p)
    assert cfg.session.max_exchanges == 20


# ── corrupt file ──────────────────────────────────────────────────────────────

def test_corrupt_toml_falls_back_to_defaults(tmp_path):
    p = _write(tmp_path, "this is not valid toml ][[\n")
    cfg = load_cli_config(p)
    assert isinstance(cfg, CLIConfig)
    assert cfg.ui.theme == "auto"


# ── force_tier case-insensitive ───────────────────────────────────────────────

def test_force_tier_normalised_to_uppercase(tmp_path):
    p = _write(tmp_path, '[model]\nforce_tier = "standard"\n')
    cfg = load_cli_config(p)
    assert cfg.model.force_tier == "STANDARD"


# ── default TOML written on first launch ──────────────────────────────────────

def test_default_toml_contains_all_sections():
    assert "[ui]" in _DEFAULT_TOML
    assert "[model]" in _DEFAULT_TOML
    assert "[session]" in _DEFAULT_TOML
