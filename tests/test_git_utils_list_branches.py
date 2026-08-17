# pylint: disable=missing-docstring, redefined-outer-name
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_git_utils_list_branches.py — COGNIREPO-301: git_utils.list_branches().
"""
from __future__ import annotations

import subprocess


def _sh(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_git_repo(repo_dir):
    _sh("init", "-q", cwd=repo_dir)
    _sh("config", "user.email", "test@example.com", cwd=repo_dir)
    _sh("config", "user.name", "Test", cwd=repo_dir)


def _commit(repo_dir, filename, message):
    (repo_dir / filename).write_text(message, encoding="utf-8")
    _sh("add", ".", cwd=repo_dir)
    _sh("commit", "-q", "-m", message, cwd=repo_dir)


def test_ahead_behind_against_default_branch(tmp_path):
    from interface.tools import git_utils

    _init_git_repo(tmp_path)
    _commit(tmp_path, "a.txt", "first")
    default = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout.strip()

    _sh("checkout", "-q", "-b", "feature/x", cwd=tmp_path)
    _commit(tmp_path, "b.txt", "second")
    _commit(tmp_path, "c.txt", "third")
    _sh("checkout", "-q", default, cwd=tmp_path)

    branches = git_utils.list_branches(repo_root=str(tmp_path))
    by_name = {b["name"]: b for b in branches}

    assert by_name[default]["is_default"] is True
    assert by_name[default]["ahead"] == 0
    assert by_name[default]["behind"] == 0

    assert by_name["feature/x"]["is_default"] is False
    assert by_name["feature/x"]["ahead"] == 2
    assert by_name["feature/x"]["behind"] == 0
    assert by_name["feature/x"]["last_commit"]["message"] == "third"


def test_empty_list_for_non_git_directory(tmp_path):
    from interface.tools import git_utils

    assert git_utils.list_branches(repo_root=str(tmp_path)) == []
