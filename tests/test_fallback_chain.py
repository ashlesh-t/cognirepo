# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Tests for the provider fallback chain in orchestrator/router.py.

Simulates quota/timeout failures to assert the router walks
anthropic → gemini → openai per provider priority.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ── Stub heavy deps BEFORE any project imports ────────────────────────────────
for _dep in ("networkx", "faiss", "sentence_transformers"):
    if _dep not in sys.modules:
        sys.modules[_dep] = MagicMock()
sys.modules["networkx"].DiGraph = MagicMock(return_value=MagicMock())

# ── Real ModelCallError (must be set before router is imported) ───────────────
class ModelCallError(Exception):
    NON_RETRYABLE_CODES = {401, 403}

    def __init__(self, message: str = "", status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


_err_mod = types.ModuleType("orchestrator.model_adapters.errors")
_err_mod.ModelCallError = ModelCallError
sys.modules["orchestrator.model_adapters.errors"] = _err_mod

# ── Minimal ModelResponse ─────────────────────────────────────────────────────
class ModelResponse:
    def __init__(self, text: str, model: str, provider: str, usage: dict | None = None):
        self.text = text
        self.model = model
        self.provider = provider
        self.usage = usage or {}


_anthropic_mod = types.ModuleType("orchestrator.model_adapters.anthropic_adapter")
_anthropic_mod.ModelResponse = ModelResponse
sys.modules["orchestrator.model_adapters.anthropic_adapter"] = _anthropic_mod

# ── Remaining heavy stubs ─────────────────────────────────────────────────────
for _mod in (
    "orchestrator.context_builder",
    "orchestrator.model_adapters.gemini_adapter",
    "orchestrator.model_adapters.grok_adapter",
    "orchestrator.model_adapters.openai_adapter",
    "graph.knowledge_graph",
    "graph.behaviour_tracker",
    "memory.episodic_memory",
):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# ── Import router (guarded against MagicMock pollution from other test files) ─
def _get_router_fns():
    """Return real _dispatch_with_fallback and _available_providers.

    If another test file has stubbed orchestrator.router as a MagicMock, pop it
    so Python re-imports the real module with our error stubs already in place.
    """
    existing = sys.modules.get("orchestrator.router")
    if existing is not None and isinstance(existing, MagicMock):
        del sys.modules["orchestrator.router"]
    from orchestrator.router import _dispatch_with_fallback, _available_providers  # noqa: E402
    return _dispatch_with_fallback, _available_providers


_dispatch_with_fallback, _available_providers = _get_router_fns()


# ── fallback chain ────────────────────────────────────────────────────────────

def test_fallback_from_anthropic_to_gemini():
    """If anthropic fails with a retryable error, falls back to gemini."""
    gemini_response = ModelResponse(
        text="gemini answer", model="gemini-2.0-flash", provider="gemini"
    )

    with (
        patch("orchestrator.router._available_providers", return_value=["anthropic", "gemini"]),
        patch("orchestrator.router._call_adapter") as mock_call,
    ):
        mock_call.side_effect = [
            ModelCallError("quota", status_code=429),
            gemini_response,
        ]
        result = _dispatch_with_fallback(
            query="test",
            primary_provider="anthropic",
            primary_model="claude-haiku-4-5",
            system_prompt="",
            tool_manifest=[],
            max_tokens=256,
        )

    assert result.text == "gemini answer"
    assert mock_call.call_count == 2


def test_all_providers_fail_raises():
    """If all providers fail, raises ModelCallError."""
    with (
        patch("orchestrator.router._available_providers", return_value=["anthropic"]),
        patch(
            "orchestrator.router._call_adapter",
            side_effect=ModelCallError("all fail", status_code=429),
        ),
    ):
        with pytest.raises(ModelCallError):
            _dispatch_with_fallback(
                query="test",
                primary_provider="anthropic",
                primary_model="claude-haiku-4-5",
                system_prompt="",
                tool_manifest=[],
                max_tokens=256,
            )


def test_non_retryable_error_does_not_try_fallback():
    """A 401 (auth) error should NOT trigger fallback (non-retryable)."""
    call_count = 0

    def _raise_401(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise ModelCallError("Unauthorized", status_code=401)

    with (
        patch("orchestrator.router._available_providers", return_value=["anthropic", "gemini"]),
        patch("orchestrator.router._call_adapter", side_effect=_raise_401),
    ):
        with pytest.raises(ModelCallError):
            _dispatch_with_fallback(
                query="test",
                primary_provider="anthropic",
                primary_model="claude-haiku-4-5",
                system_prompt="",
                tool_manifest=[],
                max_tokens=256,
            )

    assert call_count == 1  # only one attempt, no fallback


def test_local_primary_with_no_api_keys_calls_adapter_once():
    """When primary=local and no API keys are configured, _dispatch_with_fallback
    falls back to calling _call_adapter with local as the only option.
    The internal NoLocalAnswer→promote logic is covered by test_local_adapter.py."""
    standard_response = ModelResponse(
        text="promoted answer", model="claude-haiku-4-5", provider="anthropic"
    )

    with (
        # No API keys → _available_providers() = [] → ordered = [primary] = ["local"]
        patch("orchestrator.router._available_providers", return_value=[]),
        patch("orchestrator.router._call_adapter", return_value=standard_response) as mock_call,
    ):
        result = _dispatch_with_fallback(
            query="test",
            primary_provider="local",
            primary_model="local-resolver",
            system_prompt="",
            tool_manifest=[],
            max_tokens=256,
        )

    assert result.text == "promoted answer"
    assert mock_call.call_count == 1


def test_available_providers_lists_configured_keys(monkeypatch):
    """_available_providers() returns only providers with API keys set."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROK_API_KEY", raising=False)

    providers = _available_providers()
    assert "anthropic" in providers
    assert "gemini" not in providers
