# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

import os
import pytest
from config.orgs import create_org, link_repo_to_org
from retrieval.cross_repo import CrossRepoRouter
from config.paths import set_cognirepo_dir

def test_get_sibling_repos(isolated_cognirepo, tmp_path):
    repo_a = str(tmp_path / "repo_a")
    repo_b = str(tmp_path / "repo_b")
    os.makedirs(repo_a)
    os.makedirs(repo_b)
    
    create_org("my-org")
    link_repo_to_org(repo_a, "my-org")
    link_repo_to_org(repo_b, "my-org")
    
    router = CrossRepoRouter(current_repo_path=repo_a)
    siblings = router.get_sibling_repos()
    
    assert len(siblings) == 1
    assert os.path.abspath(repo_b) in siblings

def test_query_org_memories_empty(isolated_cognirepo, tmp_path):
    repo_a = str(tmp_path / "repo_a")
    os.makedirs(repo_a)
    
    router = CrossRepoRouter(current_repo_path=repo_a)
    # No org, no siblings
    assert router.query_org_memories("test") == []
