# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

import os
import pytest
from config.orgs import create_org, list_orgs, link_repo_to_org, unlink_repo_from_org, get_repo_org

def test_create_and_list_orgs(isolated_cognirepo):
    assert create_org("test-org") is True
    assert create_org("test-org") is False  # Duplicate
    
    orgs = list_orgs()
    assert "test-org" in orgs
    assert orgs["test-org"]["repos"] == []

def test_link_and_unlink_repo(isolated_cognirepo, tmp_path):
    create_org("my-org")
    repo_path = str(tmp_path / "repo1")
    os.makedirs(repo_path)
    
    assert link_repo_to_org(repo_path, "my-org") is True
    assert link_repo_to_org(repo_path, "non-existent") is False
    
    orgs = list_orgs()
    assert os.path.abspath(repo_path) in orgs["my-org"]["repos"]
    
    assert get_repo_org(repo_path) == "my-org"
    
    assert unlink_repo_from_org(repo_path, "my-org") is True
    assert get_repo_org(repo_path) is None
    
    orgs = list_orgs()
    assert os.path.abspath(repo_path) not in orgs["my-org"]["repos"]

def test_get_repo_org_none(isolated_cognirepo):
    assert get_repo_org("/some/random/path") is None
