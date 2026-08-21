# pylint: disable=missing-docstring, protected-access, redefined-outer-name
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_insights_cli_mcp.py — COGNIREPO-303 acceptance criteria.

AC1: `cognirepo insights` CLI exits 0 and prints the report path;
     `generate_insights` MCP tool payload is < 120 output tokens (tiktoken).
AC4: search_docs() finds the markdown twin under .cognirepo/docs/ post-generation,
     while other .cognirepo/ internals (e.g. index/) stay excluded from doc search.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest


def _run(*args, cwd, timeout=30):
    return subprocess.run(
        [sys.executable, "-m", "interface.cli.main"] + list(args),
        cwd=cwd, capture_output=True, text=True, timeout=timeout,
    )


@pytest.fixture
def isolated_repo(tmp_path, monkeypatch):
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / ".git").mkdir()
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / "global"))
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=False)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True, check=False)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, capture_output=True, check=False)
    (repo / "README.md").write_text("# myrepo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=False)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=False)
    init_res = _run("init", cwd=str(repo))
    assert init_res.returncode == 0, init_res.stderr
    return repo


class TestCLIInsightsCommand:
    def test_exit_zero_and_prints_path(self, isolated_repo):
        res = _run("insights", cwd=str(isolated_repo))
        assert res.returncode == 0, res.stderr
        assert "insights report written" in res.stdout.lower()
        assert str(isolated_repo) in res.stdout or ".claude" in res.stdout.lower()

    def test_writes_html_under_claude_insights(self, isolated_repo):
        _run("insights", cwd=str(isolated_repo))
        out_dir = isolated_repo / ".claude" / "insights"
        assert out_dir.is_dir()
        htmls = list(out_dir.glob("*-insights.html"))
        assert len(htmls) == 1


class TestGenerateInsightsMCPTool:
    def test_output_is_small_pointer_not_content(self, isolated_repo, monkeypatch):
        monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(isolated_repo.parent / "global"))
        from interface.server.mcp_server import generate_insights

        result = generate_insights(since="90d", repo_path=str(isolated_repo))
        assert result["status"] == "ok"
        assert result["path"].endswith("-insights.html")
        assert isinstance(result["sections"], list) and result["sections"]
        assert "updated_at" in result

        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            n_tokens = len(enc.encode(json.dumps(result)))
        except ImportError:
            n_tokens = len(json.dumps(result)) // 4  # rough fallback
        assert n_tokens < 120


class TestDocsSearchCarveOut:
    def test_finds_cognirepo_docs_but_not_other_internals(self, isolated_repo):
        cognirepo_dir = isolated_repo / ".cognirepo"
        docs_dir = cognirepo_dir / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "myrepo-insights.md").write_text(
            "# myrepo — Insights\n\nadopted zanzibar cache decision\n", encoding="utf-8"
        )
        index_dir = cognirepo_dir / "index"
        index_dir.mkdir(exist_ok=True)
        (index_dir / "secret_internal.md").write_text("zanzibar internal-only\n", encoding="utf-8")

        old_cwd = os.getcwd()
        os.chdir(isolated_repo)
        try:
            from intelligence.retrieval.docs_search import search_docs
            results = search_docs("zanzibar")
        finally:
            os.chdir(old_cwd)

        paths = [r["path"].replace("\\", "/") for r in results]
        assert any("/.cognirepo/docs/myrepo-insights.md" in p or p.startswith(".cognirepo/docs/") for p in paths)
        assert not any("/.cognirepo/index/" in p or p.startswith(".cognirepo/index/") for p in paths)
