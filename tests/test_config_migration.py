# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""Tests for Sprint 3.1 — tier rename migration."""
from __future__ import annotations
import pytest

import json
from pathlib import Path

from cli.migrate_config import migrate_config, _TIER_RENAMES
from orchestrator.classifier import ConfigMigrationError, _load_model_registry


# ── migrate_config() ──────────────────────────────────────────────────────────

def _write_config(tmp_path: Path, models: dict) -> Path:
    """Write a minimal config.json in tmp_path/.cognirepo/."""
    cr_dir = tmp_path / ".cognirepo"
    cr_dir.mkdir(exist_ok=True)
    cfg_path = cr_dir / "config.json"
    cfg_path.write_text(json.dumps({"models": models}))
    return cfg_path


def test_migrate_renames_fast_to_standard(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path, {
        "FAST":     {"provider": "gemini", "model": "gemini-2.0-flash"},
        "BALANCED": {"provider": "gemini", "model": "gemini-2.0-flash"},
        "DEEP":     {"provider": "anthropic", "model": "claude-sonnet-4-6"},
    })
    result = migrate_config(dry_run=False)

    assert result == {"FAST": "STANDARD", "BALANCED": "COMPLEX", "DEEP": "EXPERT"}
    cfg = json.loads((tmp_path / ".cognirepo" / "config.json").read_text())
    assert "STANDARD" in cfg["models"]
    assert "COMPLEX" in cfg["models"]
    assert "EXPERT" in cfg["models"]
    assert "FAST" not in cfg["models"]
    assert "BALANCED" not in cfg["models"]
    assert "DEEP" not in cfg["models"]


def test_migrate_dry_run_does_not_write(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path, {"FAST": {"provider": "gemini", "model": "x"}})
    cfg_path = tmp_path / ".cognirepo" / "config.json"
    original = cfg_path.read_text()

    result = migrate_config(dry_run=True)

    assert cfg_path.read_text() == original
    assert "FAST" in result


def test_migrate_no_op_when_already_migrated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path, {
        "STANDARD": {"provider": "gemini", "model": "gemini-2.0-flash"},
        "EXPERT": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
    })
    result = migrate_config(dry_run=False)
    assert result == {}


def test_migrate_creates_backup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path, {"FAST": {"provider": "gemini", "model": "x"}})
    migrate_config(dry_run=False)
    backup = tmp_path / ".cognirepo" / "config.json.bak"
    assert backup.exists()


def test_migrate_preserves_other_keys(tmp_path, monkeypatch):
    """Migrating should not drop non-model fields."""
    monkeypatch.chdir(tmp_path)
    cr_dir = tmp_path / ".cognirepo"
    cr_dir.mkdir(exist_ok=True)
    cfg_path = cr_dir / "config.json"
    cfg_path.write_text(json.dumps({
        "project_id": "abc-123",
        "api_port": 8000,
        "models": {"FAST": {"provider": "gemini", "model": "x"}},
    }))

    migrate_config(dry_run=False)

    cfg = json.loads(cfg_path.read_text())
    assert cfg["project_id"] == "abc-123"
    assert cfg["api_port"] == 8000


def test_migrate_file_not_found(tmp_path):
    """FileNotFoundError raised when config.json does not exist."""
    nonexistent = tmp_path / "nowhere" / "config.json"
    import cli.migrate_config as _mc
    original = _mc._config_path
    _mc._config_path = lambda: nonexistent
    try:
        with pytest.raises(FileNotFoundError):
            migrate_config(dry_run=False)
    finally:
        _mc._config_path = original


# ── classifier raises ConfigMigrationError on legacy config ───────────────────

def test_classifier_raises_on_legacy_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cr_dir = tmp_path / ".cognirepo"
    cr_dir.mkdir(exist_ok=True)
    (cr_dir / "config.json").write_text(json.dumps({
        "models": {"FAST": {"provider": "gemini", "model": "x"}}
    }))

    with pytest.raises(ConfigMigrationError) as exc_info:
        _load_model_registry()

    assert "migrate-config" in str(exc_info.value)
    assert "FAST" in str(exc_info.value)


def test_classifier_accepts_new_tier_names(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cr_dir = tmp_path / ".cognirepo"
    cr_dir.mkdir(exist_ok=True)
    (cr_dir / "config.json").write_text(json.dumps({
        "models": {
            "QUICK":    {"provider": "grok", "model": "grok-beta"},
            "STANDARD": {"provider": "gemini", "model": "gemini-2.0-flash"},
            "COMPLEX":  {"provider": "gemini", "model": "gemini-2.0-flash"},
            "EXPERT":   {"provider": "anthropic", "model": "claude-sonnet-4-6"},
        }
    }))

    registry = _load_model_registry()
    assert "STANDARD" in registry
    assert "EXPERT" in registry


# ── _TIER_RENAMES completeness ────────────────────────────────────────────────

def test_tier_renames_covers_all_old_names():
    assert "FAST" in _TIER_RENAMES
    assert "BALANCED" in _TIER_RENAMES
    assert "DEEP" in _TIER_RENAMES
    assert _TIER_RENAMES["FAST"] == "STANDARD"
    assert _TIER_RENAMES["BALANCED"] == "COMPLEX"
    assert _TIER_RENAMES["DEEP"] == "EXPERT"
