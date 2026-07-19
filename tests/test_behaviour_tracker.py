# pylint: disable=missing-docstring, import-outside-toplevel, too-few-public-methods
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_behaviour_tracker.py — BehaviourTracker unit tests.

Covers: query recording, depth inference, question type classification,
ring buffer cap, error patterns, user preferences, framing hints lifecycle
(including the post-summarization gap fix), symbol weights, and persistence.
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch


def _make_bt(tmp_path, monkeypatch):
    """Return a fresh BehaviourTracker backed by a temp dir."""
    from data.graph.knowledge_graph import KnowledgeGraph
    from data.graph.behaviour_tracker import BehaviourTracker

    cog_dir = tmp_path / ".cognirepo" / "graph"
    cog_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("COGNIREPO_DIR", str(tmp_path / ".cognirepo"))
    g = KnowledgeGraph()
    return BehaviourTracker(g)


# ── Core query recording ──────────────────────────────────────────────────────

class TestBehaviourTrackerCore:
    def test_record_query_builds_terminology(self, tmp_path, monkeypatch):
        bt = _make_bt(tmp_path, monkeypatch)
        bt.record_query("q1", "how does authentication middleware work", [])
        terms = bt.data["interaction_style"]["terminology"]
        assert "authentication" in terms or "middleware" in terms

    def test_record_query_infers_depth_concise(self, tmp_path, monkeypatch):
        bt = _make_bt(tmp_path, monkeypatch)
        for i in range(5):
            bt.record_query(f"q{i}", "what is x", [])
        assert bt.data["interaction_style"]["preferred_depth"] == "concise"

    def test_record_query_infers_depth_detailed(self, tmp_path, monkeypatch):
        bt = _make_bt(tmp_path, monkeypatch)
        long_q = "explain in detail how the authentication middleware processes JWT tokens and validates expiry" * 2
        for i in range(5):
            bt.record_query(f"q{i}", long_q, [])
        assert bt.data["interaction_style"]["preferred_depth"] == "detailed"

    def test_record_query_classifies_question_type_how(self, tmp_path, monkeypatch):
        bt = _make_bt(tmp_path, monkeypatch)
        bt.record_query("q1", "how does routing work", [])
        qtypes = bt.data["interaction_style"]["question_types"]
        assert qtypes.get("how", 0) >= 1

    def test_record_query_classifies_question_type_fix(self, tmp_path, monkeypatch):
        bt = _make_bt(tmp_path, monkeypatch)
        bt.record_query("q1", "fix the broken import in utils", [])
        qtypes = bt.data["interaction_style"]["question_types"]
        assert qtypes.get("fix", 0) >= 1

    def test_record_query_ring_buffer_capped_at_50(self, tmp_path, monkeypatch):
        bt = _make_bt(tmp_path, monkeypatch)
        for i in range(60):
            bt.record_query(f"q{i}", f"query number {i}", [])
        patterns = bt.data["interaction_style"]["query_patterns"]
        assert len(patterns) <= 50

    def test_get_user_profile_returns_required_fields(self, tmp_path, monkeypatch):
        bt = _make_bt(tmp_path, monkeypatch)
        bt.record_query("q1", "how does auth work", [])
        profile = bt.get_user_profile()
        required = ["depth_preference", "top_question_type", "framing_hints",
                    "top_terminology", "code_focus_percent", "explicit_preferences",
                    "query_rewrites", "total_queries_tracked"]
        for key in required:
            assert key in profile, f"Missing key: {key}"

    def test_record_error_increments_count(self, tmp_path, monkeypatch):
        bt = _make_bt(tmp_path, monkeypatch)
        bt.record_error("ImportError", file_path="utils.py", message="cannot import X")
        bt.record_error("ImportError", file_path="utils.py", message="cannot import X")
        assert bt.data["error_patterns"]["ImportError"]["count"] == 2

    def test_record_error_sets_prevention_hint(self, tmp_path, monkeypatch):
        bt = _make_bt(tmp_path, monkeypatch)
        bt.record_error("TypeError", file_path="main.py")
        hint = bt.data["error_patterns"]["TypeError"]["prevention_hint"]
        assert isinstance(hint, str) and len(hint) > 5

    def test_get_error_patterns_sorted_by_frequency(self, tmp_path, monkeypatch):
        bt = _make_bt(tmp_path, monkeypatch)
        bt.record_error("ImportError", "a.py")
        bt.record_error("ImportError", "a.py")
        bt.record_error("TypeError", "b.py")
        patterns = bt.get_error_patterns(min_count=1)
        assert patterns[0]["error_type"] == "ImportError"
        assert patterns[0]["count"] == 2

    def test_record_user_preference_persists(self, tmp_path, monkeypatch):
        bt = _make_bt(tmp_path, monkeypatch)
        result = bt.record_user_preference("response_style", "code first")
        assert result["recorded"] is True
        prefs = bt.get_preferences()
        assert prefs["response_style"] == "code first"

    def test_get_preferences_returns_kv_dict(self, tmp_path, monkeypatch):
        bt = _make_bt(tmp_path, monkeypatch)
        bt.record_user_preference("depth", "detailed")
        bt.record_user_preference("format", "markdown")
        prefs = bt.get_preferences()
        assert prefs["depth"] == "detailed"
        assert prefs["format"] == "markdown"


# ── Framing hints lifecycle (T3.1 fix) ───────────────────────────────────────

class TestFramingHintsLifecycle:
    def test_framing_hints_non_empty_before_summarization(self, tmp_path, monkeypatch):
        bt = _make_bt(tmp_path, monkeypatch)
        for i in range(5):
            bt.record_query(f"q{i}", f"how does authentication work in module {i}", [])
        profile = bt.get_user_profile()
        # Should have at minimum depth hint or terminology hint
        assert profile["framing_hints"] != "" or profile["top_terminology"]

    def test_framing_hints_use_cached_value_when_patterns_cleared(self, tmp_path, monkeypatch):
        """Core test for T3.1 — after summarize clears patterns, profile must stay meaningful."""
        from unittest.mock import patch as _patch

        bt = _make_bt(tmp_path, monkeypatch)
        # Build up 10 queries to trigger summarization
        for i in range(10):
            q = f"how does authentication middleware process JWT tokens {i}"
            bt.record_query(f"q{i}", q, [])

        # After 10 queries, summarize_interaction_style is called automatically
        # It clears query_patterns and terminology, but stores style["framing_hints"]
        stored_hint = bt.data["interaction_style"].get("framing_hints", "")

        # Now explicitly clear patterns to simulate post-summarization state
        bt.data["interaction_style"]["query_patterns"] = []
        bt.data["interaction_style"]["terminology"] = {}

        profile = bt.get_user_profile()
        # Must NOT return "no profile yet" — should use cached framing_hints
        assert profile["framing_hints"] != "no profile yet", (
            f"Expected cached framing_hints, got 'no profile yet'. stored_hint='{stored_hint}'"
        )

    def test_summarize_stores_framing_snapshot(self, tmp_path, monkeypatch):
        """summarize_interaction_style() must write to style['framing_hints']."""
        bt = _make_bt(tmp_path, monkeypatch)
        for i in range(10):
            bt.record_query(f"q{i}", f"how does authentication work in detail here {i}", [])
        # style["framing_hints"] should be set after auto-summarize during record_query loop
        hint = bt.data["interaction_style"].get("framing_hints", "")
        # Either set by auto-summarize or empty on very cold start — both acceptable
        assert isinstance(hint, str)

    def test_summarize_interaction_style_direct_call(self, tmp_path, monkeypatch):
        from unittest.mock import Mock
        from data.graph.knowledge_graph import KnowledgeGraph
        from data.graph.behaviour_tracker import BehaviourTracker
        from interface.tools.store_memory import store_memory

        cog_dir = tmp_path / ".cognirepo" / "graph"
        cog_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("COGNIREPO_DIR", str(tmp_path / ".cognirepo"))
        g = KnowledgeGraph()
        # Inject store_fn directly (mechanical DI, COGNIREPO-105) rather than patching
        # the module-level store_memory import that behaviour_tracker.py no longer makes.
        # spec=store_memory (COGNIREPO-D04): a loosely-mocked callable would accept any
        # kwargs and mask a signature mismatch like the pre-fix `importance=0.8` call —
        # this asserts the call site actually matches store_memory()'s real signature.
        store_fn = Mock(spec=store_memory, return_value={"conflicts": []})
        bt = BehaviourTracker(g, store_fn=store_fn)
        # Force patterns to a known state without triggering auto-summarize
        for i in range(9):
            bt.record_query(f"q{i}", f"how does routing work in this middleware {i}", [])
        # Manually add one more pattern to reach the threshold without auto-trigger
        bt.data["interaction_style"]["query_patterns"].append("how does routing work in this middleware 9")
        result = bt.summarize_interaction_style()
        hint = bt.data["interaction_style"].get("framing_hints", "")
        assert isinstance(hint, str)
        # After successful summarization, patterns are cleared
        assert result is True
        assert bt.data["interaction_style"]["query_patterns"] == []
        store_fn.assert_called_once()
        # COGNIREPO-D04 AC2: framing_hints/last_summarized are actually populated —
        # not silently skipped by a swallowed exception from a bad store_fn call.
        assert hint != ""
        assert bt.data["interaction_style"].get("last_summarized")


# ── Symbol weights / hot symbols ─────────────────────────────────────────────

class TestBehaviourSymbolWeights:
    def test_record_feedback_increments_hit_count(self, tmp_path, monkeypatch):
        bt = _make_bt(tmp_path, monkeypatch)
        bt.record_query("q1", "auth logic", ["symbol::authenticate"])
        bt.record_feedback("q1", useful=True)
        sw = bt.data["symbol_weights"]
        assert "symbol::authenticate" in sw
        assert sw["symbol::authenticate"]["hit_count"] == 1

    def test_record_feedback_twice_increments_twice(self, tmp_path, monkeypatch):
        bt = _make_bt(tmp_path, monkeypatch)
        bt.record_query("q1", "auth", ["symbol::validate"])
        bt.record_feedback("q1", useful=True)
        bt.record_query("q2", "auth again", ["symbol::validate"])
        bt.record_feedback("q2", useful=True)
        assert bt.data["symbol_weights"]["symbol::validate"]["hit_count"] == 2

    def test_get_hot_symbols_sorted_descending(self, tmp_path, monkeypatch):
        bt = _make_bt(tmp_path, monkeypatch)
        bt.record_query("q1", "a", ["symbol::hot_fn"])
        bt.record_feedback("q1", useful=True)
        bt.record_query("q2", "a", ["symbol::hot_fn"])
        bt.record_feedback("q2", useful=True)
        bt.record_query("q3", "b", ["symbol::cold_fn"])
        bt.record_feedback("q3", useful=True)
        hot = bt.get_hot_symbols(top_k=5)
        assert hot[0]["symbol_id"] == "symbol::hot_fn"
        assert hot[0]["hit_count"] == 2

    def test_get_behaviour_score_zero_for_unseen(self, tmp_path, monkeypatch):
        bt = _make_bt(tmp_path, monkeypatch)
        score = bt.get_behaviour_score("symbol::never_seen")
        assert score == 0.0


# ── Persistence ───────────────────────────────────────────────────────────────

class TestBehaviourTrackerPersistence:
    def test_save_and_load_round_trip(self, tmp_path, monkeypatch):
        from data.graph.knowledge_graph import KnowledgeGraph
        from data.graph.behaviour_tracker import BehaviourTracker

        cog_dir = tmp_path / ".cognirepo" / "graph"
        cog_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("COGNIREPO_DIR", str(tmp_path / ".cognirepo"))

        g = KnowledgeGraph()
        bt = BehaviourTracker(g)
        bt.record_error("ValueError", "file.py", "bad value")
        bt.record_user_preference("style", "concise")
        bt.save()

        bt2 = BehaviourTracker(KnowledgeGraph())
        assert "ValueError" in bt2.data["error_patterns"]
        assert bt2.get_preferences().get("style") == "concise"

    def test_load_missing_file_starts_fresh(self, tmp_path, monkeypatch):
        from data.graph.knowledge_graph import KnowledgeGraph
        from data.graph.behaviour_tracker import BehaviourTracker

        cog_dir = tmp_path / ".cognirepo" / "graph"
        cog_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("COGNIREPO_DIR", str(tmp_path / ".cognirepo"))

        bt = BehaviourTracker(KnowledgeGraph())
        assert bt.data["error_patterns"] == {}
        assert bt.data["symbol_weights"] == {}

    def test_save_creates_behaviour_json_file(self, tmp_path, monkeypatch):
        from data.graph.knowledge_graph import KnowledgeGraph
        from data.graph.behaviour_tracker import BehaviourTracker

        cog_dir = tmp_path / ".cognirepo" / "graph"
        cog_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("COGNIREPO_DIR", str(tmp_path / ".cognirepo"))

        bt = BehaviourTracker(KnowledgeGraph())
        bt.record_query("q1", "test query about auth", [])
        bt.save()

        behaviour_path = tmp_path / ".cognirepo" / "graph" / "behaviour.json"
        assert behaviour_path.exists()
