# pylint: disable=missing-docstring, redefined-outer-name, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_insights_render_write.py — COGNIREPO-302 acceptance criteria.

interface/tools/insights.py renders an InsightsModel (COGNIREPO-301) into one
self-contained HTML report + markdown twin, written idempotently.
AC1: no external URLs, both color schemes present, < 200 KB, parses as HTML.
AC2: two consecutive generate() calls -> same path, one file, updated_at advances.
AC3: every rendered fact carries data-ref; no_data sections render "no data recorded".
AC4: this file — idempotency, data-ref coverage, empty-model rendering.
"""
from __future__ import annotations

import os
import re
from html.parser import HTMLParser

import pytest

from interface.tools import insights

_NO_DATA = {"status": "no_data", "items": []}


def _empty_model(repo_root: str) -> dict:
    return {
        "meta": {"repo_root": repo_root, "since": "90d"},
        "timeline": {"status": "no_data", "entries": [], "rollup": {"total": 0, "counts": {}, "top_decisions": [], "top_errors": []}},
        "decisions": {"status": "no_data", "items": []},
        "errors": {"status": "no_data", "items": []},
        "branches": {"status": "no_data", "items": []},
        "commits_by_week": {"status": "no_data", "weeks": []},
        "hot_symbols": {"status": "no_data", "items": []},
        "index_health": {"status": "no_data", "symbols": 0, "files": 0, "last_indexed": "not indexed"},
    }


def _seeded_model(repo_root: str) -> dict:
    return {
        "meta": {"repo_root": repo_root, "since": "90d"},
        "timeline": {
            "status": "ok",
            "entries": [
                {"ts": "2026-08-01T10:00:00+00:00", "kind": "decision", "summary": "use FAISS <script>", "ref": "e_0"},
            ],
            "rollup": {"total": 1, "counts": {"decision": 1}, "top_decisions": ["use FAISS"], "top_errors": []},
        },
        "decisions": {
            "status": "ok",
            "items": [{"ts": "2026-08-01T10:00:00+00:00", "kind": "decision", "summary": "use FAISS", "ref": "e_0"}],
        },
        "errors": {
            "status": "ok",
            "items": [{"ts": "2026-08-02T10:00:00+00:00", "kind": "error", "summary": "ImportError (x2)", "ref": "ImportError"}],
        },
        "branches": {
            "status": "ok",
            "items": [{
                "name": "main", "last_commit": {"hash": "abc123def456", "date": "2026-08-01T00:00:00+00:00", "message": "init"},
                "ahead": 0, "behind": 0, "is_default": True,
            }],
        },
        "commits_by_week": {"status": "ok", "weeks": [{"week": "2026-W31", "commits": 3, "added": 10, "removed": 2}]},
        "hot_symbols": {"status": "ok", "items": [{"symbol_id": "app.py::foo", "name": "foo", "hit_count": 5}]},
        "index_health": {
            "status": "ok", "symbols": 12, "files": 3, "last_indexed": "2026-08-01T00:00:00+00:00",
            "graph_stats": {"nodes": 20, "edges": 15},
            "integrity": {"orphans": [], "dangling_files": [], "swept_at": "2026-08-01T00:00:00+00:00"},
        },
    }


class _BalanceChecker(HTMLParser):
    """Minimal well-formedness check: every non-void start tag has a matching end tag."""
    _VOID = {"meta", "link", "br", "hr", "img", "input"}

    def __init__(self):
        super().__init__()
        self.stack = []
        self.error = None

    def handle_starttag(self, tag, attrs):
        if tag not in self._VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.error = f"mismatched </{tag}>, stack={self.stack}"
        else:
            self.stack.pop()


class TestRenderEmptyModel:
    def test_no_data_sections_render_placeholder_ac3(self, tmp_path):
        html_str = insights.render(_empty_model(str(tmp_path)), generated_at="2026-08-19T00:00:00Z", updated_at="2026-08-19T00:00:00Z")
        assert html_str.count("no data recorded") >= 5  # timeline, decisions, challenges, branches, commits, hot, index

    def test_parses_as_balanced_html_ac1(self, tmp_path):
        html_str = insights.render(_empty_model(str(tmp_path)), generated_at="2026-08-19T00:00:00Z", updated_at="2026-08-19T00:00:00Z")
        checker = _BalanceChecker()
        checker.feed(html_str)
        assert checker.error is None
        assert checker.stack == []


class TestRenderSeededModel:
    def test_every_li_carries_data_ref_ac3(self, tmp_path):
        html_str = insights.render(_seeded_model(str(tmp_path)), generated_at="t1", updated_at="t2")
        li_tags = re.findall(r"<li[^>]*>", html_str)
        assert li_tags, "expected at least one <li> for the seeded model"
        for li in li_tags:
            assert 'data-ref="' in li, f"missing data-ref: {li}"

    def test_seeded_refs_present_and_escaped_ac3(self, tmp_path):
        html_str = insights.render(_seeded_model(str(tmp_path)), generated_at="t1", updated_at="t2")
        assert 'data-ref="e_0"' in html_str
        assert 'data-ref="ImportError"' in html_str
        assert 'data-ref="abc123def456"' in html_str
        # summary text is escaped, not injected as live markup
        assert "<script>" not in html_str
        assert "&lt;script&gt;" in html_str

    def test_no_external_requests_ac1(self, tmp_path):
        html_str = insights.render(_seeded_model(str(tmp_path)), generated_at="t1", updated_at="t2")
        assert not re.search(r'(src|href)\s*=\s*"https?://', html_str)
        assert "cdn." not in html_str.lower()
        assert "fonts.googleapis" not in html_str

    def test_both_color_schemes_present_ac1(self, tmp_path):
        html_str = insights.render(_seeded_model(str(tmp_path)), generated_at="t1", updated_at="t2")
        assert "prefers-color-scheme: dark" in html_str
        assert ":root" in html_str

    def test_under_200kb_ac1(self, tmp_path):
        html_str = insights.render(_seeded_model(str(tmp_path)), generated_at="t1", updated_at="t2")
        assert len(html_str.encode("utf-8")) < 200 * 1024


class TestIdempotentGenerate:
    def test_two_runs_same_path_one_file_updated_at_advances_ac2(self, tmp_path):
        repo_root = str(tmp_path)
        model = _seeded_model(repo_root)

        first = insights.generate(model, repo_root, now="2026-08-19T00:00:00+00:00")
        second = insights.generate(model, repo_root, now="2026-08-19T01:00:00+00:00")

        assert first["path"] == second["path"]
        insights_dir = os.path.join(repo_root, ".claude", "insights")
        html_files = [f for f in os.listdir(insights_dir) if f.endswith(".html")]
        assert len(html_files) == 1

        assert second["updated_at"] == "2026-08-19T01:00:00+00:00"
        assert second["generated_at"] == first["generated_at"] == "2026-08-19T00:00:00+00:00"

        with open(second["path"], encoding="utf-8") as f:
            content = f.read()
        assert 'content="2026-08-19T01:00:00+00:00"' in content  # updated_at
        assert 'content="2026-08-19T00:00:00+00:00"' in content  # generated_at preserved

    def test_markdown_twin_written_ac(self, tmp_path):
        repo_root = str(tmp_path)
        result = insights.generate(_seeded_model(repo_root), repo_root, now="2026-08-19T00:00:00+00:00")
        assert os.path.exists(result["md_path"])
        with open(result["md_path"], encoding="utf-8") as f:
            md = f.read()
        assert "use FAISS" in md
        assert "ref: e_0" in md

    def test_slugified_filename_for_unicode_repo_name(self, tmp_path):
        weird = tmp_path / "My Repo é!"
        weird.mkdir()
        result = insights.generate(_empty_model(str(weird)), str(weird), now="2026-08-19T00:00:00+00:00")
        assert re.match(r"^[a-z0-9-]+-insights\.html$", os.path.basename(result["path"]))
        # display name stays verbatim inside the rendered content
        with open(result["path"], encoding="utf-8") as f:
            assert "My Repo" in f.read()


class TestWriteAtomicity:
    def test_write_creates_claude_insights_dir(self, tmp_path):
        repo_root = str(tmp_path)
        html_str = insights.render(_empty_model(repo_root), generated_at="t1", updated_at="t2")
        path = insights.write(html_str, repo_root)
        assert path.startswith(os.path.join(repo_root, ".claude", "insights"))
        assert os.path.exists(path)


@pytest.mark.parametrize("name,expected", [
    ("simple-repo", "simple-repo"),
    ("My Repo", "my-repo"),
    ("repo é ü", "repo"),
    ("", "repo"),
])
def test_slugify(name, expected):
    assert insights._slugify(name) == expected
