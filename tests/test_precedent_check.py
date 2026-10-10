# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_precedent_check.py — COGNIREPO-704 acceptance criteria.

check_precedent() surfaces conflicts between a proposed instruction and recorded decisions/
CLAUDE.md invariants. ALWAYS advisory -- never blocks, never raises on a conflict.
"""
from __future__ import annotations


class TestInvariantChecks:
    def test_model_literal_instruction_flags_invariant_with_citation_and_alternative(self):
        """AC1 + AC4 (seed/validation case): a request to hardcode a model-ID literal outside
        classifier.py flags the model_names_only_in_classifier invariant, citing
        COGNIREPO-700-D01 -- the concrete proof this mechanism works, per the story's own
        validation fixture (the live violations D01 found and fixed)."""
        from intelligence.precedent_check import check_precedent

        result = check_precedent(
            "hardcode claude-sonnet-4-6 as the default model_id in the new adapter file"
        )
        assert result["advisory"] is True
        assert len(result["conflicts"]) == 1
        conflict = result["conflicts"][0]
        assert conflict["type"] == "invariant"
        assert conflict["name"] == "model_names_only_in_classifier"
        assert "classifier.py" in conflict["citation"]
        assert conflict["related_defect"] == "COGNIREPO-700-D01"
        assert "suggested_alternative" in conflict and conflict["suggested_alternative"]

    def test_informational_model_question_does_not_fire(self):
        """AC2: an ordinary informational question about models -- no hardcoding intent --
        must not trigger the invariant (no intent_pattern match)."""
        from intelligence.precedent_check import check_precedent

        result = check_precedent("what model does the COMPLEX tier use")
        assert result["conflicts"] == []

    def test_faiss_bypass_instruction_flags_retrieval_invariant(self):
        from intelligence.precedent_check import check_precedent

        result = check_precedent("just call FAISS directly from the new tool instead of going through hybrid.py")
        names = [c["name"] for c in result["conflicts"]]
        assert "retrieval_only_via_hybrid" in names

    def test_cross_tool_call_instruction_flags_statelessness_invariant(self):
        from intelligence.precedent_check import check_precedent

        result = check_precedent("make a tool that calls another tool directly to share logic")
        names = [c["name"] for c in result["conflicts"]]
        assert "tools_stateless_single_entry_point" in names

    def test_storage_outside_cognirepo_instruction_flags_storage_invariant(self):
        from intelligence.precedent_check import check_precedent

        result = check_precedent("store this new cache file outside .cognirepo so it survives a reset")
        names = [c["name"] for c in result["conflicts"]]
        assert "storage_under_cognirepo" in names


class TestNoFalsePositives:
    def test_routine_requests_produce_zero_conflicts(self):
        """AC2: ordinary requests with no relevant precedent -- zero friction, no 'well
        actually' on routine asks."""
        from intelligence.precedent_check import check_precedent

        routine = [
            "add a new CLI command for exporting metrics",
            "explain how model routing works",
            "fix the flaky test in test_router.py",
            "write a function that stores this in the database",
            "implement pagination for the search_episodes results",
            "what is jwt",
        ]
        for instruction in routine:
            result = check_precedent(instruction)
            assert result["conflicts"] == [], f"false positive on: {instruction!r}"


class TestDecisionChecks:
    def test_reversal_instruction_matching_a_decision_is_flagged(self):
        from data.memory.episodic_memory import log_event
        from intelligence.precedent_check import check_precedent

        log_event(
            "decision: use FAISS for vector search",
            metadata={"type": "decision", "summary": "use FAISS for vector search"},
        )
        result = check_precedent("let us replace FAISS with Pinecone for vector search")
        decision_conflicts = [c for c in result["conflicts"] if c["type"] == "decision"]
        assert len(decision_conflicts) == 1
        assert "FAISS" in decision_conflicts[0]["citation"]

    def test_same_topic_without_reversal_cue_is_not_flagged(self):
        """The decision search is gated behind a reversal cue -- an ordinary request that
        happens to share a topic with a past decision must not fire (AC2)."""
        from data.memory.episodic_memory import log_event
        from intelligence.precedent_check import check_precedent

        log_event(
            "decision: use FAISS for vector search",
            metadata={"type": "decision", "summary": "use FAISS for vector search"},
        )
        result = check_precedent("add a new field to the vector search results")
        assert result["conflicts"] == []

    def test_reversal_cue_with_no_decisions_recorded_is_not_flagged(self):
        from intelligence.precedent_check import check_precedent

        result = check_precedent("let's replace the caching layer with something else")
        assert result["conflicts"] == []


class TestAdvisoryOnly:
    def test_result_is_always_advisory_true(self):
        """AC3: the mechanism's output is advisory (a structured finding), not a hard stop."""
        from intelligence.precedent_check import check_precedent

        assert check_precedent("hardcode claude-sonnet-4-6 as the default")["advisory"] is True
        assert check_precedent("what is jwt")["advisory"] is True

    def test_never_raises_even_with_broken_decision_search(self, monkeypatch):
        """A broken decision search must never crash the (always-advisory) check itself."""
        import intelligence.precedent_check as pc

        def _boom(_instruction):
            raise RuntimeError("simulated failure")

        monkeypatch.setattr(pc, "_check_decisions", _boom)
        result = pc.check_precedent("let's replace FAISS with something else")
        assert result["advisory"] is True
        assert isinstance(result["conflicts"], list)

    def test_conflicts_key_present_even_when_empty(self):
        """conflicts is an explicit empty list, not omitted -- 'checked, found nothing' rather
        than silence."""
        from intelligence.precedent_check import check_precedent

        result = check_precedent("what is jwt")
        assert "conflicts" in result
        assert result["conflicts"] == []


class TestGetAgentBootstrapUnaffected:
    def test_check_precedent_is_a_separate_tool_not_folded_into_bootstrap(self):
        """COGNIREPO-704 is a distinct, explicitly-invoked check (runs before an arbitrary
        instruction is implemented) -- unlike 702, it does not fold into get_agent_bootstrap's
        session-start payload, since there's no single 'instruction' at bootstrap time."""
        from interface.server.mcp_server import get_agent_bootstrap

        result = get_agent_bootstrap()
        assert "conflicts" not in result
        assert "check_precedent" not in result
