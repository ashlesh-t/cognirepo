# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
cli/migrate_config.py — automatic config.json migration for the v0.5.0 tier rename.

Old tier names:  FAST → STANDARD,  BALANCED → COMPLEX,  DEEP → EXPERT

Usage
-----
    cognirepo migrate-config           # in-place update
    cognirepo migrate-config --dry-run # preview without writing
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from config.paths import get_path

logger = logging.getLogger(__name__)

_TIER_RENAMES: dict[str, str] = {
    "FAST":     "STANDARD",
    "BALANCED": "COMPLEX",
    "DEEP":     "EXPERT",
}


def _config_path() -> Path:
    return Path(get_path("config.json"))


def migrate_config(dry_run: bool = False) -> dict[str, str]:
    """
    Rename deprecated tier keys in ``.cognirepo/config.json``.

    Returns a dict of {old_key: new_key} for all renames that were (or would be) applied.
    Returns an empty dict when no migration was needed.

    Parameters
    ----------
    dry_run : If True, show what would change but do not write anything.
    """
    cfg_path = _config_path()
    if not cfg_path.exists():
        raise FileNotFoundError(f"config.json not found: {cfg_path}")

    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)

    models: dict = cfg.get("models", {})
    renames_applied: dict[str, str] = {}

    for old_key, new_key in _TIER_RENAMES.items():
        if old_key in models:
            renames_applied[old_key] = new_key

    if not renames_applied:
        print("  config.json already uses new tier names — no migration needed.")
        return {}

    if dry_run:
        print("  DRY RUN — no changes written.")
        for old, new in renames_applied.items():
            print(f"    {old!r} → {new!r}")
        return renames_applied

    # Back up the original before writing
    backup_path = cfg_path.with_suffix(".json.bak")
    shutil.copy2(cfg_path, backup_path)
    print(f"  Backup written: {backup_path}")

    # Apply renames
    new_models: dict = {}
    for key, value in models.items():
        new_key = _TIER_RENAMES.get(key, key)
        new_models[new_key] = value
    cfg["models"] = new_models

    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    for old, new in renames_applied.items():
        print(f"  Renamed: {old!r} → {new!r}")

    print(f"\n  Migration complete. Updated: {cfg_path}")
    print("  Old config backed up to:", backup_path)
    return renames_applied


def run_migrate_config(dry_run: bool = False) -> int:
    """Entry point for the CLI command. Returns exit code."""
    print("CogniRepo config migration — v0.5.0 tier rename\n")
    try:
        migrate_config(dry_run=dry_run)
        return 0
    except FileNotFoundError as exc:
        print(f"  Error: {exc}")
        print("  Run: cognirepo init (to create the project first)")
        return 1
    except Exception as exc:  # pylint: disable=broad-except
        print(f"  Migration failed: {exc}")
        return 1
