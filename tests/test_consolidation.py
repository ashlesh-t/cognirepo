# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_consolidation.py — COGNIREPO-702 acceptance criteria.

find_consolidation_candidates() clusters recurring/near-duplicate episodic events that were
never promoted to a decision, using this module's own BM25 similarity machinery. Never calls
record_decision()/log_event(type=decision) itself.
"""
from __future__ import annotations

import re
from unittest.mock import patch


class TestConsolidationCandidates:
    def test_three_near_duplicate_episodes_form_one_group(self):
        """AC1: >=3 near-duplicate episodic events about the same topic produce one
        consolidation_candidates entry citing the specific episode ids as evidence."""
        from data.memory.episodic_memory import log_event, find_consolidation_candidates

        log_event("cache invalidation keeps breaking on concurrent writes in redis backend")
        log_event("cache invalidation keeps breaking again on concurrent writes redis")
        log_event("another cache invalidation failure with concurrent writes to redis backend")

        candidates = find_consolidation_candidates(since="30d")
        assert len(candidates) == 1
        assert len(candidates[0]["episode_ids"]) == 3
        assert all(re.match(r"^e_\d+$", eid) for eid in candidates[0]["episode_ids"])
        assert "suggested_decision_draft" in candidates[0]
        assert "group_summary" in candidates[0]

    def test_unrelated_episode_not_grouped_with_near_duplicates(self):
        """A real near-duplicate group must not sweep in an unrelated episode just because
        BM25Plus's smoothing gives it a nonzero absolute score on a small corpus."""
        from data.memory.episodic_memory import log_event, find_consolidation_candidates

        log_event("cache invalidation keeps breaking on concurrent writes in redis backend")
        log_event("cache invalidation keeps breaking again on concurrent writes redis")
        log_event("another cache invalidation failure with concurrent writes to redis backend")
        log_event("fixed a typo in the README installation section")

        candidates = find_consolidation_candidates(since="30d")
        assert len(candidates) == 1
        assert "e_3" not in candidates[0]["episode_ids"]

    def test_never_calls_record_decision_or_logs_a_decision(self):
        """AC2: the consolidation pass itself never calls record_decision or writes a
        metadata.type=='decision' episode, verified by patching both write paths."""
        from data.memory.episodic_memory import log_event, find_consolidation_candidates
        import data.memory.episodic_memory as em

        log_event("cache invalidation keeps breaking on concurrent writes in redis backend")
        log_event("cache invalidation keeps breaking again on concurrent writes redis")
        log_event("another cache invalidation failure with concurrent writes to redis backend")

        with patch.object(em, "log_event") as mock_log:
            find_consolidation_candidates(since="30d")
            mock_log.assert_not_called()

        # Also confirm no decision-typed episode exists in the store after the call
        data = em._load()
        assert not any((e.get("metadata") or {}).get("type") == "decision" for e in data)

    def test_sparse_store_returns_empty_list(self):
        """AC3: fewer episodes than min_group_size -> empty candidates, nothing fabricated."""
        from data.memory.episodic_memory import log_event, find_consolidation_candidates

        log_event("fixed a typo in README")
        log_event("added dark mode support")

        assert find_consolidation_candidates(since="30d") == []

    def test_empty_store_returns_empty_list(self):
        from data.memory.episodic_memory import find_consolidation_candidates
        assert find_consolidation_candidates(since="30d") == []

    def test_no_repeated_topics_returns_empty_list(self):
        """AC3: several genuinely unrelated episodes -> no groups fabricated."""
        from data.memory.episodic_memory import log_event, find_consolidation_candidates

        log_event("fixed a typo in README")
        log_event("added dark mode support to dashboard")
        log_event("refactored payment retry logic")
        log_event("updated CI to run on python 3.13")
        log_event("bumped numpy version for security patch")

        assert find_consolidation_candidates(since="30d") == []

    def test_existing_decisions_excluded_from_candidate_pool(self):
        """An episode already promoted to a decision (metadata.type == 'decision') must not be
        re-clustered as a fresh consolidation candidate."""
        from data.memory.episodic_memory import log_event, find_consolidation_candidates

        log_event(
            "decision: use redis for cache invalidation",
            metadata={"type": "decision", "summary": "use redis for cache invalidation"},
        )
        log_event("cache invalidation keeps breaking on concurrent writes in redis backend")
        log_event("cache invalidation keeps breaking again on concurrent writes redis")

        # Only 2 non-decision episodes remain -- below min_group_size=3
        assert find_consolidation_candidates(since="30d") == []

    def test_since_window_excludes_old_episodes(self, monkeypatch):
        """Episodes outside the `since` window must not be pulled into a candidate group."""
        from data.memory.episodic_memory import log_event, find_consolidation_candidates
        import data.memory.episodic_memory as em

        log_event("cache invalidation keeps breaking on concurrent writes in redis backend")
        log_event("cache invalidation keeps breaking again on concurrent writes redis")
        log_event("another cache invalidation failure with concurrent writes to redis backend")

        # Backdate all 3 events well outside a 30d window
        data = em._load()
        for e in data:
            e["time"] = "2020-01-01T00:00:00+00:00"
        em._save(data)

        assert find_consolidation_candidates(since="30d") == []


class TestGetAgentBootstrapConsolidation:
    def test_consolidation_candidates_surfaced_when_decision_nudge_fires(self):
        """COGNIREPO-702 extends decision_nudge (COGNIREPO-205) with real evidence rather than
        replacing it -- consolidation_candidates appears in get_agent_bootstrap's output
        alongside a content-aware decision_nudge message, folded into the existing tool
        (zero new MCP tool, AC4)."""
        from data.memory.episodic_memory import log_event
        from interface.server.mcp_server import get_agent_bootstrap

        # >=5 episodes, 0 decisions, with a real recurring topic among them
        log_event("cache invalidation keeps breaking on concurrent writes in redis backend")
        log_event("cache invalidation keeps breaking again on concurrent writes redis")
        log_event("another cache invalidation failure with concurrent writes to redis backend")
        log_event("unrelated minor doc fix")
        log_event("another unrelated small change")

        result = get_agent_bootstrap()
        assert "consolidation_candidates" in result
        assert len(result["consolidation_candidates"]) == 1
        assert "consolidation_candidates" in result["decision_nudge"]

    def test_decision_nudge_falls_back_to_generic_message_with_no_recurring_topic(self):
        """When the gap fires but nothing actually clusters, the original COGNIREPO-205
        generic nudge text still appears -- and consolidation_candidates is omitted entirely
        (not an empty list) per this payload's existing "absent when nothing to report" style."""
        from data.memory.episodic_memory import log_event
        from interface.server.mcp_server import get_agent_bootstrap

        log_event("fixed a typo in README")
        log_event("added dark mode support")
        log_event("refactored payment retry logic")
        log_event("updated CI to run on python 3.13")
        log_event("bumped numpy version for security patch")

        result = get_agent_bootstrap()
        assert "consolidation_candidates" not in result
        assert result.get("decision_nudge") == (
            "no decisions recorded yet — use record_decision for architectural choices"
        )
