# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_classifier_auto_model.py — #270 (COG-6).

`cognirepo setup` writes ``"model": {"provider": "auto", "model": "auto"}``. The provider then comes from whichever
API key is set, and the model for each tier must come from *that provider's* own defaults. It used to be a hardcoded
Anthropic id for every provider, so a Gemini-only (or OpenAI-only) key sent ``claude-*`` to Gemini (or OpenAI), which
answered 404.

No model id is written out here (see test_model_id_invariant.py): the expectations come from the classifier's own
tables.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from intelligence.orchestrator import router
from intelligence.orchestrator.classifier import (
    _DEFAULT_TIER_REGISTRY,
    _load_model_registry,
    classify,
    default_model_for,
)

_KEY_VARS = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "GROK_API_KEY")
_TIERS = ("STANDARD", "COMPLEX", "EXPERT")
_AUTO = {"provider": "auto", "model": "auto"}


@pytest.fixture(autouse=True)
def _no_keys(monkeypatch):
    """A developer's own keys must not leak in and decide the provider."""
    for var in _KEY_VARS:
        monkeypatch.delenv(var, raising=False)


def _write_model_block(block: dict) -> None:
    path = Path(".cognirepo") / "config.json"  # the test fixture runs in a temp dir with .cognirepo/ already made
    path.write_text(json.dumps({"model": block}), encoding="utf-8")


@pytest.mark.parametrize("env_var,provider", [
    ("ANTHROPIC_API_KEY", "anthropic"),
    ("GEMINI_API_KEY", "gemini"),
    ("GOOGLE_API_KEY", "gemini"),
    ("OPENAI_API_KEY", "openai"),
    ("GROK_API_KEY", "grok"),
])
def test_auto_model_belongs_to_the_resolved_provider(monkeypatch, env_var, provider):
    monkeypatch.setenv(env_var, "k")
    _write_model_block(_AUTO)

    registry = _load_model_registry()

    assert registry["QUICK"] == {"provider": "local", "model": "local-resolver"}
    for tier in _TIERS:
        assert registry[tier] == {"provider": provider, "model": default_model_for(provider, tier)}
        assert registry[tier]["model"], "a provider with a shipped default must never end up with an empty model"
        if provider != "anthropic":
            assert registry[tier]["model"] != _DEFAULT_TIER_REGISTRY[tier]["model"], "an Anthropic id was sent elsewhere"


@pytest.mark.parametrize("keys", [(), ("ANTHROPIC_API_KEY",)])
def test_auto_is_unchanged_for_anthropic_and_for_no_key(monkeypatch, keys):
    for var in keys:
        monkeypatch.setenv(var, "k")
    _write_model_block(_AUTO)

    registry = _load_model_registry()

    for tier in _TIERS:
        assert registry[tier] == _DEFAULT_TIER_REGISTRY[tier]


@pytest.mark.parametrize("keys,provider", [
    (("ANTHROPIC_API_KEY", "GEMINI_API_KEY"), "anthropic"),
    (("GEMINI_API_KEY", "OPENAI_API_KEY"), "gemini"),
    (("GOOGLE_API_KEY", "GROK_API_KEY"), "gemini"),
    # Grok is considered last, so an install that already had an OpenAI key keeps resolving to OpenAI.
    (("OPENAI_API_KEY", "GROK_API_KEY"), "openai"),
])
def test_auto_provider_priority(monkeypatch, keys, provider):
    for var in keys:
        monkeypatch.setenv(var, "k")
    _write_model_block(_AUTO)

    assert {_load_model_registry()[tier]["provider"] for tier in _TIERS} == {provider}


def test_a_model_the_user_names_is_kept_for_every_tier(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    _write_model_block({"provider": "auto", "model": "my-own-model"})

    registry = _load_model_registry()

    assert {(registry[t]["provider"], registry[t]["model"]) for t in _TIERS} == {("gemini", "my-own-model")}


def test_an_explicit_provider_wins_over_the_keys_that_are_set(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    _write_model_block({"provider": "gemini", "model": "auto"})

    registry = _load_model_registry()

    for tier in _TIERS:
        assert registry[tier] == {"provider": "gemini", "model": default_model_for("gemini", tier)}


def test_what_the_router_sends_a_gemini_key_is_a_gemini_model(monkeypatch):
    """The reported path end to end: classify, then the model the router resolves for that provider. With no
    discovery cache (the case before `cognirepo models refresh`) nothing else can correct the model."""
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    _write_model_block(_AUTO)

    clf = classify("refactor the retrieval architecture and compare the design trade-offs across modules")

    assert clf.tier != "QUICK", "the query must reach a model for this test to mean anything"
    assert clf.provider == "gemini"
    sent = router._model_for(clf.provider, clf.tier, clf.provider, clf.model)  # pylint: disable=protected-access
    assert sent == default_model_for("gemini", clf.tier)
