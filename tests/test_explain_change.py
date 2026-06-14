# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_explain_change.py — unit tests for explain_change and git_utils.
Uses mocked git subprocess output throughout (no live git calls).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


# ── git_utils unit tests ──────────────────────────────────────────────────────

class TestGitUtils:
    _SAMPLE_LOG = (
        "COMMIT_SEP\n"
        "abc1234\n"
        "Alice Dev\n"
        "2026-03-15 10:00:00 +0000\n"
        "Fix JWT expiry bug\n"
        "+    new_line = True\n"
        "+    another_new = 1\n"
        "-    old_line = False\n"
        "@@ -10,5 +10,6 @@ def verify_token\n"
    )

    def test_parse_since_days(self):
        from tools.git_utils import _parse_since
        result = _parse_since("7d")
        # should be a YYYY-MM-DD date
        import re
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", result)

    def test_parse_since_iso_passthrough(self):
        from tools.git_utils import _parse_since
        result = _parse_since("2026-01-01")
        assert result == "2026-01-01"

    def test_parse_since_weeks(self):
        from tools.git_utils import _parse_since
        r7d = _parse_since("7d")
        r1w = _parse_since("1w")
        assert r7d == r1w

    def test_parse_git_log_output(self):
        from tools.git_utils import _parse_git_log_output
        commits = _parse_git_log_output(self._SAMPLE_LOG)
        assert len(commits) == 1
        c = commits[0]
        assert c["hash"] == "abc1234"
        assert c["author"] == "Alice Dev"
        assert c["message"] == "Fix JWT expiry bug"
        assert c["diff_summary"]["added"] == 2
        assert c["diff_summary"]["removed"] == 1
        assert c["diff_summary"]["hunks"] == 1

    def test_parse_empty_log(self):
        from tools.git_utils import _parse_git_log_output
        result = _parse_git_log_output("")
        assert result == []

    def test_git_log_patch_returns_list(self):
        from tools.git_utils import git_log_patch
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = self._SAMPLE_LOG
        with patch("tools.git_utils.subprocess.run", return_value=mock_proc):
            with patch("tools.git_utils._find_git_root", return_value="/fake/repo"):
                result = git_log_patch("auth.py", since="7d", repo_root="/fake/repo")
        assert isinstance(result, list)
        assert len(result) == 1

    def test_git_not_found_raises(self):
        from tools.git_utils import git_log_patch, GitNotFoundError
        import subprocess
        with patch("tools.git_utils.subprocess.run", side_effect=FileNotFoundError):
            with patch("tools.git_utils._find_git_root", return_value="/fake/repo"):
                with pytest.raises(GitNotFoundError):
                    git_log_patch("auth.py", repo_root="/fake/repo")

    def test_nonzero_returncode_returns_empty(self):
        from tools.git_utils import git_log_patch
        mock_proc = MagicMock()
        mock_proc.returncode = 128
        mock_proc.stdout = ""
        with patch("tools.git_utils.subprocess.run", return_value=mock_proc):
            with patch("tools.git_utils._find_git_root", return_value="/fake/repo"):
                result = git_log_patch("auth.py", repo_root="/fake/repo")
        assert result == []


# ── explain_change unit tests ─────────────────────────────────────────────────

import pytest


class TestExplainChange:
    _MOCK_COMMITS = [
        {
            "hash": "abc1234",
            "author": "Alice",
            "date": "2026-03-15",
            "message": "Fix JWT expiry",
            "diff_summary": {"added": 2, "removed": 1, "hunks": 1},
        }
    ]

    def test_returns_required_keys(self):
        from tools.explain_change import explain_change
        with patch("tools.explain_change.git_log_patch", return_value=self._MOCK_COMMITS):
            with patch("tools.explain_change.episodic_bm25_filter", return_value=[]):
                result = explain_change("auth.py")
        assert "target" in result
        assert "since" in result
        assert "git_summary" in result
        assert "episodic_context" in result

    def test_target_preserved(self):
        from tools.explain_change import explain_change
        with patch("tools.explain_change.git_log_patch", return_value=[]):
            with patch("tools.explain_change.episodic_bm25_filter", return_value=[]):
                result = explain_change("retrieval/hybrid.py", since="30d")
        assert result["target"] == "retrieval/hybrid.py"
        assert result["since"] == "30d"

    def test_git_summary_totals(self):
        from tools.explain_change import explain_change
        commits = [
            {"hash": "a", "author": "X", "date": "2026-01-01", "message": "m1",
             "diff_summary": {"added": 5, "removed": 2, "hunks": 1}},
            {"hash": "b", "author": "X", "date": "2026-01-02", "message": "m2",
             "diff_summary": {"added": 3, "removed": 1, "hunks": 2}},
        ]
        with patch("tools.explain_change.git_log_patch", return_value=commits):
            with patch("tools.explain_change.episodic_bm25_filter", return_value=[]):
                result = explain_change("auth.py")
        assert result["git_summary"]["total_added"] == 8
        assert result["git_summary"]["total_removed"] == 3
        assert len(result["git_summary"]["commits"]) == 2

    def test_no_git_repo_returns_error(self):
        from tools.explain_change import explain_change
        from tools.git_utils import GitNotFoundError
        with patch("tools.explain_change.git_log_patch", side_effect=GitNotFoundError("not a git repository")):
            result = explain_change("auth.py")
        assert "error" in result
        assert "not a git repository" in result["error"]

    def test_episodic_context_included(self):
        from tools.explain_change import explain_change
        ep_events = [
            {"event": "fixed JWT expiry bug in auth", "time": "2026-03-15", "metadata": {}}
        ]
        with patch("tools.explain_change.git_log_patch", return_value=self._MOCK_COMMITS):
            with patch("tools.explain_change.episodic_bm25_filter", return_value=ep_events):
                result = explain_change("auth.py")
        assert len(result["episodic_context"]) == 1
        assert "JWT" in result["episodic_context"][0]["event"]

    def test_episodic_failure_doesnt_crash(self):
        """If episodic search fails, git summary is still returned."""
        from tools.explain_change import explain_change
        with patch("tools.explain_change.git_log_patch", return_value=self._MOCK_COMMITS):
            with patch("tools.explain_change.episodic_bm25_filter", side_effect=RuntimeError("fail")):
                result = explain_change("auth.py")
        assert "git_summary" in result
        assert result["episodic_context"] == []

    def test_empty_git_history_still_returns_structure(self):
        from tools.explain_change import explain_change
        with patch("tools.explain_change.git_log_patch", return_value=[]):
            with patch("tools.explain_change.episodic_bm25_filter", return_value=[]):
                result = explain_change("new_file.py")
        assert result["git_summary"]["commits"] == []
        assert result["git_summary"]["total_added"] == 0
