# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_context_pack.py — unit tests for the context_pack tool.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch

_tiktoken_available = pytest.importorskip("tiktoken", reason="tiktoken not installed")


class TestContextPack:
    def _mock_candidates(self):
        return [
            {
                "text": "FUNCTION hybrid_retrieve in retrieval/hybrid.py:249 — Single entry",
                "final_score": 0.9,
                "source": "ast",
            },
            {
                "text": "semantic memory result about authentication",
                "final_score": 0.7,
                "source": "semantic",
            },
        ]

    def test_returns_required_keys(self):
        from interface.tools.context_pack import context_pack
        with patch("interface.tools.context_pack.hybrid_retrieve", return_value=[]):
            with patch("interface.tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("test query")
        assert "query" in result
        assert "token_count" in result
        assert "sections" in result
        assert "truncated" in result

    def test_query_preserved(self):
        from interface.tools.context_pack import context_pack
        with patch("interface.tools.context_pack.hybrid_retrieve", return_value=[]):
            with patch("interface.tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("my specific query")
        assert result["query"] == "my specific query"

    def test_max_tokens_not_exceeded(self):
        from interface.tools.context_pack import context_pack
        candidates = self._mock_candidates() * 10  # many candidates
        with patch("interface.tools.context_pack.hybrid_retrieve", return_value=candidates):
            with patch("interface.tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("query", max_tokens=200)
        # token_count should be <= max_tokens + 5% tolerance
        assert result["token_count"] <= 210

    def test_include_episodic_false_omits_episodic(self):
        from interface.tools.context_pack import context_pack
        ep_mock = [{"event": "deployed auth", "time": "2026-01-01T00:00:00Z", "metadata": {}}]
        with patch("interface.tools.context_pack.hybrid_retrieve", return_value=[]):
            with patch("interface.tools.context_pack.episodic_bm25_filter", return_value=ep_mock) as mock_ep:
                result = context_pack("query", include_episodic=False)
        mock_ep.assert_not_called()
        episodic_sections = [s for s in result["sections"] if s["type"] == "episodic"]
        assert len(episodic_sections) == 0

    def test_include_symbols_false_skips_retrieval(self):
        from interface.tools.context_pack import context_pack
        with patch("interface.tools.context_pack.hybrid_retrieve") as mock_ret:
            with patch("interface.tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("query", include_symbols=False)
        mock_ret.assert_not_called()

    def test_sections_have_required_fields(self):
        from interface.tools.context_pack import context_pack
        candidates = [
            {"text": "authentication logic description", "final_score": 0.8, "source": "semantic"}
        ]
        with patch("interface.tools.context_pack.hybrid_retrieve", return_value=candidates):
            with patch("interface.tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("auth query")
        for section in result["sections"]:
            assert "type" in section
            assert "source" in section
            assert "score" in section
            assert "content" in section

    def test_episodic_sections_included(self):
        from interface.tools.context_pack import context_pack
        ep_events = [
            {"event": "fixed JWT bug", "time": "2026-01-01T00:00:00Z", "metadata": {"env": "prod"}},
        ]
        with patch("interface.tools.context_pack.hybrid_retrieve", return_value=[]):
            with patch("interface.tools.context_pack.episodic_bm25_filter", return_value=ep_events):
                result = context_pack("JWT auth", include_episodic=True)
        episodic_sections = [s for s in result["sections"] if s["type"] == "episodic"]
        assert len(episodic_sections) == 1
        assert "fixed JWT bug" in episodic_sections[0]["content"]

    def test_truncated_flag_set_when_budget_exceeded(self):
        from interface.tools.context_pack import context_pack
        # create many large candidates to force truncation
        large_candidates = [
            {"text": "x " * 200, "final_score": 0.9 - i * 0.01, "source": "semantic"}
            for i in range(20)
        ]
        with patch("interface.tools.context_pack.hybrid_retrieve", return_value=large_candidates):
            with patch("interface.tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("query", max_tokens=100)
        # either truncated is True or token_count is within budget
        assert result["truncated"] is True or result["token_count"] <= 105

    def test_token_count_accurate(self):
        from interface.tools.context_pack import context_pack, _count_tokens
        candidates = [
            {"text": "some code content here", "final_score": 0.8, "source": "semantic"}
        ]
        with patch("interface.tools.context_pack.hybrid_retrieve", return_value=candidates):
            with patch("interface.tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("query", max_tokens=2000)
        # token_count must match sum of section token counts within 5%
        actual = sum(_count_tokens(s["content"]) for s in result["sections"])
        reported = result["token_count"]
        if actual > 0:
            assert abs(reported - actual) / actual <= 0.05


class TestDelegationHints:
    """COGNIREPO-502 — delegation_hints in context_pack output."""

    @staticmethod
    def _write(tmp_path, rel_path, lines):
        p = tmp_path / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _ast_candidate(self, rel_path, line, component_id, score=0.9):
        return {
            "text": f"FUNCTION fn in {rel_path}:{line} — helper",
            "final_score": score,
            "source": "ast",
            "component_id": component_id,
        }

    def test_present_with_todos_for_two_groups(self, tmp_path):
        """AC1: two-group fixture -> hints present, each with its TODO/FIXME lines."""
        from interface.tools.context_pack import context_pack

        self._write(tmp_path, "mod_a.py", ["def a():", "    pass", "    # TODO: refactor this"])
        self._write(tmp_path, "mod_b.py", ["def b():", "    pass", "    # FIXME: handle edge case"])
        candidates = [
            self._ast_candidate("mod_a.py", 1, "g0"),
            self._ast_candidate("mod_b.py", 1, "g1"),
        ]
        with patch("interface.tools.context_pack.hybrid_retrieve", return_value=candidates):
            with patch("interface.tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("query", repo_root=str(tmp_path))

        hints = result.get("delegation_hints")
        assert hints is not None
        assert {h["group"] for h in hints} == {"g0", "g1"}
        for h in hints:
            assert h["reason"] == "no shared import/call path"
            assert h["files"]
        by_group = {h["group"]: h for h in hints}
        assert by_group["g0"]["todos"][0]["text"].endswith("TODO: refactor this")
        assert by_group["g1"]["todos"][0]["text"].endswith("FIXME: handle edge case")

    def test_absent_when_single_group(self, tmp_path):
        """AC1: connected fixture (one component_id) -> key absent entirely, not an empty list."""
        from interface.tools.context_pack import context_pack

        self._write(tmp_path, "mod_a.py", ["def a():", "    pass"])
        self._write(tmp_path, "mod_b.py", ["def b():", "    pass"])
        candidates = [
            self._ast_candidate("mod_a.py", 1, "g0"),
            self._ast_candidate("mod_b.py", 1, "g0"),
        ]
        with patch("interface.tools.context_pack.hybrid_retrieve", return_value=candidates):
            with patch("interface.tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("query", repo_root=str(tmp_path))
        assert "delegation_hints" not in result

    def test_absent_when_no_component_id(self, tmp_path):
        """Hits with no resolvable component_id (grouping gated off, or non-graph hits) never
        produce hints — matches hybrid.py's "no key at all" contract, not an empty groups dict."""
        from interface.tools.context_pack import context_pack

        self._write(tmp_path, "mod_a.py", ["def a():", "    pass"])
        candidates = [
            {"text": f"FUNCTION fn in mod_a.py:1 — helper", "final_score": 0.9, "source": "ast"},
        ]
        with patch("interface.tools.context_pack.hybrid_retrieve", return_value=candidates):
            with patch("interface.tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("query", repo_root=str(tmp_path))
        assert "delegation_hints" not in result

    def test_two_group_token_cost_is_small(self, tmp_path):
        """AC2: added output for the two-group case stays in the few-dozen-token budget."""
        from interface.tools.context_pack import context_pack, _count_tokens
        import json

        self._write(tmp_path, "mod_a.py", ["def a():", "    pass"])
        self._write(tmp_path, "mod_b.py", ["def b():", "    pass"])
        candidates = [
            self._ast_candidate("mod_a.py", 1, "g0"),
            self._ast_candidate("mod_b.py", 1, "g1"),
        ]
        with patch("interface.tools.context_pack.hybrid_retrieve", return_value=candidates):
            with patch("interface.tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("query", repo_root=str(tmp_path))
        hints = result["delegation_hints"]
        assert _count_tokens(json.dumps(hints)) <= 80  # ~60 tokens expected, generous margin

    def test_dropped_on_tight_budget_core_content_intact(self, tmp_path):
        """AC3: a budget too tight for hints drops them silently — core sections still pack."""
        from interface.tools.context_pack import context_pack

        self._write(tmp_path, "mod_a.py", ["def a():", "    pass", "    # TODO: one"])
        self._write(tmp_path, "mod_b.py", ["def b():", "    pass", "    # TODO: two"])
        candidates = [
            self._ast_candidate("mod_a.py", 1, "g0"),
            self._ast_candidate("mod_b.py", 1, "g1"),
        ]
        # Enough budget for the two small code sections, not enough left over for hints.
        with patch("interface.tools.context_pack.hybrid_retrieve", return_value=candidates):
            with patch("interface.tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("query", repo_root=str(tmp_path), max_tokens=25)
        assert "delegation_hints" not in result
        assert len(result["sections"]) >= 1  # core content untouched by the drop

    def test_todos_capped_at_three_per_group(self, tmp_path):
        lines = ["def a():"] + [f"    # TODO: item {i}" for i in range(6)]
        self._write(tmp_path, "mod_a.py", lines)
        self._write(tmp_path, "mod_b.py", ["def b():", "    pass"])
        from interface.tools.context_pack import context_pack

        candidates = [
            self._ast_candidate("mod_a.py", 1, "g0"),
            self._ast_candidate("mod_b.py", 1, "g1"),
        ]
        with patch("interface.tools.context_pack.hybrid_retrieve", return_value=candidates):
            with patch("interface.tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("query", repo_root=str(tmp_path))
        by_group = {h["group"]: h for h in result["delegation_hints"]}
        assert len(by_group["g0"]["todos"]) == 3


class TestContextPackRepoPaths:
    def test_context_pack_with_repo_path_returns_valid_shape(self, isolated_cognirepo, tmp_path):
        """MCP context_pack(repo_path=...) must return structured result, not crash."""
        from interface.server.mcp_server import context_pack
        with patch("interface.tools.context_pack.hybrid_retrieve", return_value=[]):
            with patch("interface.tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("authentication", repo_path=str(tmp_path))
        assert "query" in result
        assert "sections" in result
        assert "token_count" in result

    def test_context_pack_nonexistent_repo_path_returns_gracefully(self, isolated_cognirepo, tmp_path):
        """MCP context_pack with a non-initialized repo_path returns empty sections, not a crash."""
        from interface.server.mcp_server import context_pack
        with patch("interface.tools.context_pack.hybrid_retrieve", return_value=[]):
            with patch("interface.tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("anything", repo_path=str(tmp_path / "no_such_dir"))
        assert isinstance(result, dict)
        assert "sections" in result

    def test_context_pack_repo_path_preserves_query(self, isolated_cognirepo, tmp_path):
        """Query string must survive the repo_path scoping."""
        from interface.server.mcp_server import context_pack
        with patch("interface.tools.context_pack.hybrid_retrieve", return_value=[]):
            with patch("interface.tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("my test query", repo_path=str(tmp_path))
        assert result["query"] == "my test query"
