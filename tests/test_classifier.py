# pylint: disable=missing-docstring, unnecessary-lambda, import-outside-toplevel, too-few-public-methods, duplicate-code
# pylint: disable=redefined-outer-name, unused-argument, broad-exception-caught, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tests/test_classifier.py — all 7 signals + edge cases + hard overrides.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def classify():
    from orchestrator.classifier import classify as _classify
    return _classify


class TestHardOverrides:
    def test_single_token_fast(self, classify):
        r = classify("x")
        assert r.tier == "FAST"
        assert "single_token" in r.overrides

    def test_empty_single_token(self, classify):
        r = classify("auth")
        assert r.tier == "FAST"

    def test_full_context_phrase_deep(self, classify):
        r = classify("give me full context on this")
        assert r.tier == "DEEP"
        assert "full_context_phrase" in r.overrides

    def test_all_related_phrase_deep(self, classify):
        r = classify("show everything related to auth")
        assert r.tier == "DEEP"

    def test_error_trace_minimum_balanced(self, classify):
        r = classify("TypeError: 'NoneType' object is not subscriptable at line 42")
        assert r.tier in ("BALANCED", "DEEP")
        assert "error_trace" in r.overrides

    def test_traceback_keyword(self, classify):
        r = classify("Traceback (most recent call last): File auth.py line 10")
        assert r.tier in ("BALANCED", "DEEP")


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
        assert r.signals.get("imperative_abstract", 0) == 4.0

    def test_build_keyword_imperative(self, classify):
        r = classify("build a microservice for this")
        assert r.signals.get("imperative_abstract", 0) == 4.0


class TestTierBoundaries:
    def test_fast_tier(self, classify):
        r = classify("list all files")
        assert r.tier == "FAST"

    def test_balanced_tier(self, classify):
        r = classify("why is verify_token slow compared to check_session")
        assert r.tier in ("BALANCED", "DEEP")

    def test_deep_tier_full_override(self, classify):
        r = classify("complete context for this project")
        assert r.tier == "DEEP"

    def test_score_returned(self, classify):
        r = classify("show me auth.py")
        assert isinstance(r.score, float)

    def test_model_and_provider_returned(self, classify):
        r = classify("what is jwt")
        assert r.model
        assert r.provider in ("anthropic", "gemini", "openai")

    def test_force_model_overrides_model_id(self, classify):
        r = classify("show me files", force_model="claude-opus-4-6")
        assert r.model == "claude-opus-4-6"
        assert r.tier == "FAST"  # tier still computed
