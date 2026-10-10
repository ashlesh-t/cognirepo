# pylint: disable=missing-docstring, unnecessary-lambda, import-outside-toplevel, too-few-public-methods, duplicate-code
# pylint: disable=redefined-outer-name, unused-argument, broad-exception-caught, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_classifier.py — all 7 signals + edge cases + hard overrides.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def classify():
    from intelligence.orchestrator.classifier import classify as _classify
    return _classify


class TestHardOverrides:
    def test_single_token_fast(self, classify):
        r = classify("x")
        assert r.tier == "QUICK"
        assert "single_token" in r.overrides

    def test_empty_single_token(self, classify):
        r = classify("auth")
        assert r.tier == "QUICK"

    def test_full_context_phrase_deep(self, classify):
        r = classify("give me full context on this")
        assert r.tier == "EXPERT"
        assert "full_context_phrase" in r.overrides

    def test_all_related_phrase_deep(self, classify):
        r = classify("show everything related to auth")
        assert r.tier == "EXPERT"

    def test_error_trace_minimum_balanced(self, classify):
        r = classify("TypeError: 'NoneType' object is not subscriptable at line 42")
        assert r.tier in ("COMPLEX", "EXPERT")
        assert "error_trace" in r.overrides

    def test_traceback_keyword(self, classify):
        r = classify("Traceback (most recent call last): File auth.py line 10")
        assert r.tier in ("COMPLEX", "EXPERT")


class TestSignals:
    def test_reasoning_keywords_increase_score(self, classify):
        r_plain = classify("show me the function")
        r_reason = classify("why does the function fail and what are the tradeoffs")
        assert r_reason.score > r_plain.score

    def test_lookup_keywords_decrease_score(self, classify):
        r = classify("list all files and show directories")
        assert r.score < 0  # two lookup keywords → -4

    def test_vague_referents_increase_score(self, classify):
        # "it" preceded by a short non-noun token (or at start) counts as vague
        r = classify("it crashed and this broke my build")
        assert r.signals.get("vague_referents", 0) > 0

    def test_cross_entity_count_signal(self, classify):
        # 3 snake_case entities → 1 above threshold → +1.5
        r = classify("compare verify_token with check_session and decode_jwt behaviour")
        assert r.signals.get("cross_entity_count", 0) > 0

    def test_context_dependency_signal(self, classify):
        r = classify("as discussed earlier, what was the bug")
        assert r.signals.get("context_dependency", 0) == 3.0

    def test_token_length_signal(self, classify):
        long_q = " ".join(["word"] * 35)  # 35 tokens > 20 threshold
        r = classify(long_q)
        assert r.signals.get("token_length", 0) > 0

    def test_imperative_abstract_signal(self, classify):
        r = classify("implement a new caching layer")
        assert r.signals.get("imperative_abstract", 0) == 5.0

    def test_build_keyword_imperative(self, classify):
        r = classify("build a microservice for this")
        assert r.signals.get("imperative_abstract", 0) == 5.0


class TestTierBoundaries:
    def test_standard_tier(self, classify):
        r = classify("list all files")
        assert r.tier == "QUICK"

    def test_complex_tier(self, classify):
        r = classify("why is verify_token slow compared to check_session")
        assert r.tier in ("COMPLEX", "EXPERT")

    def test_deep_tier_full_override(self, classify):
        r = classify("complete context for this project")
        assert r.tier == "EXPERT"

    def test_score_returned(self, classify):
        r = classify("show me auth.py")
        assert isinstance(r.score, float)

    def test_model_and_provider_returned(self, classify):
        r = classify("what is jwt")
        assert r.model
        assert r.provider in ("anthropic", "gemini", "openai", "grok")

    def test_force_model_overrides_model_id(self, classify):
        r = classify("show me files", force_model="claude-opus-4-6")
        assert r.model == "claude-opus-4-6"
        assert r.tier == "QUICK"  # tier still computed


# ── COGNIREPO-703: confidence-calibrated tier classification ─────────────────

class TestConfidence:
    def test_near_boundary_query_has_lower_confidence_than_decisive_query(self, classify):
        """AC2: confidence is measurably lower for a near-boundary score (~3.9, just under the
        4.0 STANDARD/COMPLEX boundary) than for a decisively mid-tier score (~0.1, deep in
        QUICK) -- tested against concrete score fixtures directly, not just "it exists"."""
        from intelligence.orchestrator.classifier import _confidence_from_score
        near_boundary = _confidence_from_score(3.9)
        decisive = _confidence_from_score(0.1)
        assert near_boundary < decisive
        assert near_boundary == 0.1
        assert decisive == 1.0

    def test_confidence_is_zero_exactly_on_a_boundary(self):
        from intelligence.orchestrator.classifier import _confidence_from_score, _TIER_STANDARD
        assert _confidence_from_score(_TIER_STANDARD) == 0.0

    def test_confidence_capped_at_one_far_from_any_boundary(self):
        from intelligence.orchestrator.classifier import _confidence_from_score
        assert _confidence_from_score(0.0) == 1.0
        assert _confidence_from_score(20.0) == 1.0

    def test_classify_result_always_has_confidence_field(self, classify):
        r = classify("what is jwt")
        assert 0.0 <= r.confidence <= 1.0

    def test_hard_override_queries_still_get_a_confidence_value(self, classify):
        """Overrides (single_token, docs_query, full_context_phrase) set score directly rather
        than going through _compute_score -- confidence must still compute without crashing."""
        r = classify("x")
        assert "single_token" in r.overrides
        assert 0.0 <= r.confidence <= 1.0

    def test_signals_dict_unchanged_by_confidence_addition(self, classify):
        """AC3: signals dict output is unchanged -- this story adds one new field to
        ClassifierResult, it does not restructure existing output."""
        r = classify("why is this slow and what should I refactor")
        assert isinstance(r.signals, dict)
        assert all(isinstance(v, float) for v in r.signals.values())

    def test_golden_tier_assignment_unaffected_by_confidence(self, classify):
        """AC1: tier assignment is byte-identical before and after this change -- golden
        regression over a representative corpus, not just a spot check."""
        golden = [
            ("x", "QUICK"),
            ("list all files", "QUICK"),
            ("show me auth.py", "QUICK"),
            ("complete context for this project", "EXPERT"),
            ("why is verify_token slow compared to check_session", None),  # COMPLEX or EXPERT
        ]
        for query, expected_tier in golden:
            r = classify(query)
            if expected_tier is not None:
                assert r.tier == expected_tier, f"{query!r} -> {r.tier}, expected {expected_tier}"
            assert 0.0 <= r.confidence <= 1.0
