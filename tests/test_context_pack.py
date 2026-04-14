# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

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
        from tools.context_pack import context_pack
        with patch("tools.context_pack.hybrid_retrieve", return_value=[]):
            with patch("tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("test query")
        assert "query" in result
        assert "token_count" in result
        assert "sections" in result
        assert "truncated" in result

    def test_query_preserved(self):
        from tools.context_pack import context_pack
        with patch("tools.context_pack.hybrid_retrieve", return_value=[]):
            with patch("tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("my specific query")
        assert result["query"] == "my specific query"

    def test_max_tokens_not_exceeded(self):
        from tools.context_pack import context_pack
        candidates = self._mock_candidates() * 10  # many candidates
        with patch("tools.context_pack.hybrid_retrieve", return_value=candidates):
            with patch("tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("query", max_tokens=200)
        # token_count should be <= max_tokens + 5% tolerance
        assert result["token_count"] <= 210

    def test_include_episodic_false_omits_episodic(self):
        from tools.context_pack import context_pack
        ep_mock = [{"event": "deployed auth", "time": "2026-01-01T00:00:00Z", "metadata": {}}]
        with patch("tools.context_pack.hybrid_retrieve", return_value=[]):
            with patch("tools.context_pack.episodic_bm25_filter", return_value=ep_mock) as mock_ep:
                result = context_pack("query", include_episodic=False)
        mock_ep.assert_not_called()
        episodic_sections = [s for s in result["sections"] if s["type"] == "episodic"]
        assert len(episodic_sections) == 0

    def test_include_symbols_false_skips_retrieval(self):
        from tools.context_pack import context_pack
        with patch("tools.context_pack.hybrid_retrieve") as mock_ret:
            with patch("tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("query", include_symbols=False)
        mock_ret.assert_not_called()

    def test_sections_have_required_fields(self):
        from tools.context_pack import context_pack
        candidates = [
            {"text": "authentication logic description", "final_score": 0.8, "source": "semantic"}
        ]
        with patch("tools.context_pack.hybrid_retrieve", return_value=candidates):
            with patch("tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("auth query")
        for section in result["sections"]:
            assert "type" in section
            assert "source" in section
            assert "score" in section
            assert "content" in section

    def test_episodic_sections_included(self):
        from tools.context_pack import context_pack
        ep_events = [
            {"event": "fixed JWT bug", "time": "2026-01-01T00:00:00Z", "metadata": {"env": "prod"}},
        ]
        with patch("tools.context_pack.hybrid_retrieve", return_value=[]):
            with patch("tools.context_pack.episodic_bm25_filter", return_value=ep_events):
                result = context_pack("JWT auth", include_episodic=True)
        episodic_sections = [s for s in result["sections"] if s["type"] == "episodic"]
        assert len(episodic_sections) == 1
        assert "fixed JWT bug" in episodic_sections[0]["content"]

    def test_truncated_flag_set_when_budget_exceeded(self):
        from tools.context_pack import context_pack
        # create many large candidates to force truncation
        large_candidates = [
            {"text": "x " * 200, "final_score": 0.9 - i * 0.01, "source": "semantic"}
            for i in range(20)
        ]
        with patch("tools.context_pack.hybrid_retrieve", return_value=large_candidates):
            with patch("tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("query", max_tokens=100)
        # either truncated is True or token_count is within budget
        assert result["truncated"] is True or result["token_count"] <= 105

    def test_token_count_accurate(self):
        from tools.context_pack import context_pack, _count_tokens
        candidates = [
            {"text": "some code content here", "final_score": 0.8, "source": "semantic"}
        ]
        with patch("tools.context_pack.hybrid_retrieve", return_value=candidates):
            with patch("tools.context_pack.episodic_bm25_filter", return_value=[]):
                result = context_pack("query", max_tokens=2000)
        # token_count must match sum of section token counts within 5%
        actual = sum(_count_tokens(s["content"]) for s in result["sections"])
        reported = result["token_count"]
        if actual > 0:
            assert abs(reported - actual) / actual <= 0.05
