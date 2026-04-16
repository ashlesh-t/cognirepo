# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Logic for managing local repository organizations.

Orgs allow grouping multiple repositories together so findings and context
can be shared across them.
"""
import json
import os
import logging
from config.paths import get_orgs_path

logger = logging.getLogger(__name__)

def _load_orgs() -> dict:
    path = get_orgs_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load orgs.json: %s", exc)
        return {}

def _save_orgs(orgs: dict) -> None:
    path = get_orgs_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(orgs, f, indent=2)
    except OSError as exc:
        logger.error("Failed to save orgs.json: %s", exc)

def create_org(name: str) -> bool:
    """Create a new local organization. Returns True if successful."""
    orgs = _load_orgs()
    if name in orgs:
        return False
    orgs[name] = {"repos": []}
    _save_orgs(orgs)
    return True

def list_orgs() -> dict:
    """Return the global orgs registry."""
    return _load_orgs()

def link_repo_to_org(repo_path: str, org_name: str) -> bool:
    """Link a repository path to an organization."""
    orgs = _load_orgs()
    if org_name not in orgs:
        return False
    
    abs_path = os.path.abspath(repo_path)
    if abs_path not in orgs[org_name]["repos"]:
        orgs[org_name]["repos"].append(abs_path)
        _save_orgs(orgs)
    return True

def unlink_repo_from_org(repo_path: str, org_name: str) -> bool:
    """Remove a repository path from an organization."""
    orgs = _load_orgs()
    if org_name not in orgs:
        return False
    
    abs_path = os.path.abspath(repo_path)
    if abs_path in orgs[org_name]["repos"]:
        orgs[org_name]["repos"].remove(abs_path)
        _save_orgs(orgs)
        return True
    return False

def get_repo_org(repo_path: str) -> str | None:
    """Find which org a repository belongs to (if any)."""
    abs_path = os.path.abspath(repo_path)
    orgs = _load_orgs()
    for name, data in orgs.items():
        if abs_path in data.get("repos", []):
            return name
    return None
