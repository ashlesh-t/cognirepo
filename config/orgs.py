# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Logic for managing local repository organizations and projects.

Schema (orgs.json):
{
  "<org>": {
    "repos": [...],          # org-level repos (backward compat)
    "projects": {
      "<project>": {
        "description": "",
        "repos": [...],
        "created_at": "ISO8601",
        "shared_memory_path": "~/.cognirepo/projects/<org>/<project>/"
      }
    }
  }
}
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from config.paths import get_orgs_path

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(orgs, f, indent=2)
    except OSError as exc:
        logger.error("Failed to save orgs.json: %s", exc)


# ── org-level (backward compat) ───────────────────────────────────────────────

def create_org(name: str) -> bool:
    """Create a new local organization. Returns True if created, False if exists."""
    orgs = _load_orgs()
    if name in orgs:
        return False
    orgs[name] = {"repos": [], "projects": {}}
    _save_orgs(orgs)
    return True


def list_orgs() -> dict:
    """Return the global orgs registry."""
    return _load_orgs()


def link_repo_to_org(repo_path: str, org_name: str) -> bool:
    """Link a repository path to an organization (org-level, not project-scoped)."""
    orgs = _load_orgs()
    if org_name not in orgs:
        return False
    abs_path = os.path.abspath(repo_path)
    if abs_path not in orgs[org_name].setdefault("repos", []):
        orgs[org_name]["repos"].append(abs_path)
        _save_orgs(orgs)
    return True


def unlink_repo_from_org(repo_path: str, org_name: str) -> bool:
    """Remove a repository path from an organization."""
    orgs = _load_orgs()
    if org_name not in orgs:
        return False
    abs_path = os.path.abspath(repo_path)
    repos = orgs[org_name].get("repos", [])
    if abs_path in repos:
        repos.remove(abs_path)
        _save_orgs(orgs)
        return True
    return False


def get_repo_org(repo_path: str) -> str | None:
    """Find which org a repository belongs to (org-level or via project)."""
    abs_path = os.path.abspath(repo_path)
    orgs = _load_orgs()
    for org_name, data in orgs.items():
        if abs_path in data.get("repos", []):
            return org_name
        for proj in data.get("projects", {}).values():
            if abs_path in proj.get("repos", []):
                return org_name
    return None


# ── project-level ─────────────────────────────────────────────────────────────

def create_project(org_name: str, project_name: str, description: str = "") -> bool:
    """Create a project within an org. Creates org if absent. Returns True on success."""
    orgs = _load_orgs()
    if org_name not in orgs:
        orgs[org_name] = {"repos": [], "projects": {}}
    projects = orgs[org_name].setdefault("projects", {})
    if project_name in projects:
        return False
    shared = str(
        Path.home() / ".cognirepo" / "projects" / org_name / project_name
    )
    projects[project_name] = {
        "description": description,
        "repos": [],
        "created_at": _now(),
        "shared_memory_path": shared,
    }
    _save_orgs(orgs)
    return True


def list_projects(org_name: str) -> dict[str, dict]:
    """Return {project_name: project_dict} for org_name. Empty dict if org absent."""
    orgs = _load_orgs()
    return orgs.get(org_name, {}).get("projects", {})


def link_repo_to_project(repo_path: str, org_name: str, project_name: str) -> bool:
    """Link repo to a project. Project must exist. Returns True on success."""
    orgs = _load_orgs()
    projects = orgs.get(org_name, {}).get("projects", {})
    if project_name not in projects:
        return False
    abs_path = os.path.abspath(repo_path)
    repos = projects[project_name].setdefault("repos", [])
    if abs_path not in repos:
        repos.append(abs_path)
        _save_orgs(orgs)
    return True


def unlink_repo_from_project(repo_path: str, org_name: str, project_name: str) -> bool:
    """Remove repo from a project. Returns True if removed."""
    orgs = _load_orgs()
    projects = orgs.get(org_name, {}).get("projects", {})
    if project_name not in projects:
        return False
    abs_path = os.path.abspath(repo_path)
    repos = projects[project_name].get("repos", [])
    if abs_path in repos:
        repos.remove(abs_path)
        _save_orgs(orgs)
        return True
    return False


def get_repo_project(repo_path: str) -> tuple[str, str] | None:
    """Return (org_name, project_name) if repo is linked to a project, else None."""
    abs_path = os.path.abspath(repo_path)
    orgs = _load_orgs()
    for org_name, data in orgs.items():
        for proj_name, proj in data.get("projects", {}).items():
            if abs_path in proj.get("repos", []):
                return (org_name, proj_name)
    return None


def get_project_repos(org_name: str, project_name: str) -> list[str]:
    """Return list of repo paths in a project. Empty list if not found."""
    orgs = _load_orgs()
    return orgs.get(org_name, {}).get("projects", {}).get(project_name, {}).get("repos", [])


def get_shared_memory_path(org_name: str, project_name: str) -> Path:
    """Return the shared memory directory path for a project."""
    orgs = _load_orgs()
    stored = (
        orgs.get(org_name, {})
        .get("projects", {})
        .get(project_name, {})
        .get("shared_memory_path")
    )
    if stored:
        return Path(stored).expanduser()
    return Path.home() / ".cognirepo" / "projects" / org_name / project_name
