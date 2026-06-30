# pylint: disable=missing-docstring, import-outside-toplevel, broad-exception-caught
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""tests/test_config_orgs_extended.py — Coverage for config/orgs.py (56% → 85%)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def orgs_path(tmp_path):
    orgs_file = tmp_path / "orgs.json"
    import core.config.orgs as orgs_mod
    with patch.object(orgs_mod, "get_orgs_path", return_value=str(orgs_file)):
        yield str(orgs_file), orgs_mod


# ── create_org / list_orgs ────────────────────────────────────────────────────

def test_create_org_new(orgs_path):
    _, orgs_mod = orgs_path
    result = orgs_mod.create_org("myorg")
    assert result is True
    orgs = orgs_mod.list_orgs()
    assert "myorg" in orgs


def test_create_org_duplicate(orgs_path):
    _, orgs_mod = orgs_path
    orgs_mod.create_org("myorg")
    result = orgs_mod.create_org("myorg")
    assert result is False


def test_list_orgs_empty(orgs_path):
    _, orgs_mod = orgs_path
    result = orgs_mod.list_orgs()
    assert isinstance(result, dict)
    assert result == {}


def test_get_org_by_id(orgs_path):
    _, orgs_mod = orgs_path
    orgs_mod.create_org("testorg")
    orgs = orgs_mod.list_orgs()
    org_id = orgs["testorg"]["id"]
    result = orgs_mod.get_org_by_id(org_id)
    assert result is not None
    assert result[0] == "testorg"


def test_get_org_by_id_not_found(orgs_path):
    _, orgs_mod = orgs_path
    result = orgs_mod.get_org_by_id("nonexistent-id")
    assert result is None


# ── link_repo_to_org / unlink_repo_from_org ───────────────────────────────────

def test_link_repo_to_org(orgs_path, tmp_path):
    _, orgs_mod = orgs_path
    orgs_mod.create_org("myorg")
    result = orgs_mod.link_repo_to_org(str(tmp_path), "myorg")
    assert result is True
    orgs = orgs_mod.list_orgs()
    abs_path = os.path.abspath(str(tmp_path))
    assert abs_path in orgs["myorg"]["repos"]


def test_link_repo_to_nonexistent_org(orgs_path, tmp_path):
    _, orgs_mod = orgs_path
    result = orgs_mod.link_repo_to_org(str(tmp_path), "nonexistent")
    assert result is False


def test_link_repo_duplicate(orgs_path, tmp_path):
    _, orgs_mod = orgs_path
    orgs_mod.create_org("myorg")
    orgs_mod.link_repo_to_org(str(tmp_path), "myorg")
    orgs_mod.link_repo_to_org(str(tmp_path), "myorg")  # duplicate
    orgs = orgs_mod.list_orgs()
    abs_path = os.path.abspath(str(tmp_path))
    assert orgs["myorg"]["repos"].count(abs_path) == 1


def test_unlink_repo_from_org(orgs_path, tmp_path):
    _, orgs_mod = orgs_path
    orgs_mod.create_org("myorg")
    orgs_mod.link_repo_to_org(str(tmp_path), "myorg")
    result = orgs_mod.unlink_repo_from_org(str(tmp_path), "myorg")
    assert result is True
    orgs = orgs_mod.list_orgs()
    abs_path = os.path.abspath(str(tmp_path))
    assert abs_path not in orgs["myorg"]["repos"]


def test_unlink_repo_not_in_org(orgs_path, tmp_path):
    _, orgs_mod = orgs_path
    orgs_mod.create_org("myorg")
    result = orgs_mod.unlink_repo_from_org(str(tmp_path), "myorg")
    assert result is False


def test_unlink_repo_nonexistent_org(orgs_path, tmp_path):
    _, orgs_mod = orgs_path
    result = orgs_mod.unlink_repo_from_org(str(tmp_path), "nonexistent")
    assert result is False


# ── create_project / list_projects ───────────────────────────────────────────

def test_create_project_new(orgs_path):
    _, orgs_mod = orgs_path
    orgs_mod.create_org("myorg")
    result = orgs_mod.create_project("myorg", "proj1", description="test project")
    assert result is True
    projects = orgs_mod.list_projects("myorg")
    assert "proj1" in projects


def test_create_project_creates_org(orgs_path):
    _, orgs_mod = orgs_path
    result = orgs_mod.create_project("neworg", "proj1")
    assert result is True
    orgs = orgs_mod.list_orgs()
    assert "neworg" in orgs


def test_create_project_duplicate(orgs_path):
    _, orgs_mod = orgs_path
    orgs_mod.create_project("myorg", "proj1")
    result = orgs_mod.create_project("myorg", "proj1")
    assert result is False


def test_list_projects_empty_org(orgs_path):
    _, orgs_mod = orgs_path
    result = orgs_mod.list_projects("nonexistent")
    assert result == {}


# ── link_repo_to_project / unlink_repo_from_project ──────────────────────────

def test_link_repo_to_project(orgs_path, tmp_path):
    _, orgs_mod = orgs_path
    orgs_mod.create_project("myorg", "proj1")
    result = orgs_mod.link_repo_to_project(str(tmp_path), "myorg", "proj1")
    assert result is True
    repos = orgs_mod.get_project_repos("myorg", "proj1")
    abs_path = os.path.abspath(str(tmp_path))
    assert abs_path in repos


def test_link_repo_to_nonexistent_project(orgs_path, tmp_path):
    _, orgs_mod = orgs_path
    result = orgs_mod.link_repo_to_project(str(tmp_path), "myorg", "nonexistent")
    assert result is False


def test_unlink_repo_from_project(orgs_path, tmp_path):
    _, orgs_mod = orgs_path
    orgs_mod.create_project("myorg", "proj1")
    orgs_mod.link_repo_to_project(str(tmp_path), "myorg", "proj1")
    result = orgs_mod.unlink_repo_from_project(str(tmp_path), "myorg", "proj1")
    assert result is True


def test_unlink_repo_from_project_not_there(orgs_path, tmp_path):
    _, orgs_mod = orgs_path
    orgs_mod.create_project("myorg", "proj1")
    result = orgs_mod.unlink_repo_from_project(str(tmp_path), "myorg", "proj1")
    assert result is False


def test_unlink_repo_nonexistent_project(orgs_path, tmp_path):
    _, orgs_mod = orgs_path
    result = orgs_mod.unlink_repo_from_project(str(tmp_path), "myorg", "nonexistent")
    assert result is False


# ── get_repo_project ──────────────────────────────────────────────────────────

def test_get_repo_project_found(orgs_path, tmp_path):
    _, orgs_mod = orgs_path
    orgs_mod.create_project("myorg", "proj1")
    orgs_mod.link_repo_to_project(str(tmp_path), "myorg", "proj1")
    result = orgs_mod.get_repo_project(str(tmp_path))
    assert result == ("myorg", "proj1")


def test_get_repo_project_not_found(orgs_path, tmp_path):
    _, orgs_mod = orgs_path
    result = orgs_mod.get_repo_project(str(tmp_path))
    assert result is None


# ── purge_stale_repos ─────────────────────────────────────────────────────────

def test_purge_stale_repos_nonexistent(orgs_path, tmp_path):
    _, orgs_mod = orgs_path
    result = orgs_mod.purge_stale_repos("nonexistent")
    assert result == []


def test_purge_stale_repos_removes_missing(orgs_path, tmp_path):
    _, orgs_mod = orgs_path
    orgs_mod.create_org("myorg")
    fake_path = str(tmp_path / "nonexistent_repo")
    orgs_mod.link_repo_to_org(fake_path, "myorg")
    removed = orgs_mod.purge_stale_repos("myorg")
    abs_path = os.path.abspath(fake_path)
    assert abs_path in removed


def test_purge_stale_repos_keeps_existing(orgs_path, tmp_path):
    _, orgs_mod = orgs_path
    orgs_mod.create_org("myorg")
    orgs_mod.link_repo_to_org(str(tmp_path), "myorg")
    removed = orgs_mod.purge_stale_repos("myorg")
    assert len(removed) == 0


# ── get_shared_memory_path ────────────────────────────────────────────────────

def test_get_shared_memory_path_from_stored(orgs_path):
    _, orgs_mod = orgs_path
    orgs_mod.create_project("myorg", "proj1", description="test")
    path = orgs_mod.get_shared_memory_path("myorg", "proj1")
    assert isinstance(path, Path)


def test_get_shared_memory_path_fallback(orgs_path):
    _, orgs_mod = orgs_path
    path = orgs_mod.get_shared_memory_path("noorg", "noproj")
    assert isinstance(path, Path)
    assert "noproj" in str(path)


# ── _load_orgs backfill ───────────────────────────────────────────────────────

def test_load_orgs_backfills_id(orgs_path):
    orgs_file, orgs_mod = orgs_path
    # Write orgs.json without "id" field
    with open(orgs_file, "w") as f:
        json.dump({"testorg": {"repos": [], "projects": {}}}, f)
    orgs = orgs_mod._load_orgs()
    assert "id" in orgs["testorg"]
