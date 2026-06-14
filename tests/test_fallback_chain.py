# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Tests for the provider fallback chain in orchestrator/router.py.

Simulates quota/timeout failures to assert the router walks
anthropic → gemini → openai per provider priority.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# ── Stub heavy deps BEFORE any project imports ────────────────────────────────
# Try to import each dep first; only stub if the real package is absent.
_HEAVY_DEPS_STUBBED: list[str] = []
for _dep in ("faiss", "fastembed"):
    try:
        __import__(_dep)
    except ImportError:
        sys.modules[_dep] = MagicMock()
        _HEAVY_DEPS_STUBBED.append(_dep)
try:
    __import__("networkx")
except ImportError:
    _nx_mock = MagicMock()
    _nx_mock.DiGraph = MagicMock(return_value=MagicMock())
    sys.modules["networkx"] = _nx_mock
    _HEAVY_DEPS_STUBBED.append("networkx")

# ── Use real ModelCallError and ModelResponse (both modules are importable) ───
from orchestrator.model_adapters.errors import ModelCallError  # noqa: E402
from orchestrator.model_adapters.anthropic_adapter import ModelResponse  # noqa: E402

# ── Remaining heavy stubs ─────────────────────────────────────────────────────
# Only stub modules that are NOT already importable (avoid polluting real installs).
_STUBBED_BY_THIS_FILE: list[str] = []

def _try_real_import(mod: str) -> bool:
    """Return True if the real module can be imported without error."""
    import importlib  # pylint: disable=import-outside-toplevel
    try:
        importlib.import_module(mod)
        return True
    except Exception:  # pylint: disable=broad-except
        return False

for _mod in (
    "orchestrator.context_builder",
    "orchestrator.model_adapters.gemini_adapter",
    "orchestrator.model_adapters.grok_adapter",
    "orchestrator.model_adapters.openai_adapter",
    "graph.behaviour_tracker",
    "memory.episodic_memory",
):
    if _mod not in sys.modules and not _try_real_import(_mod):
        sys.modules[_mod] = MagicMock()
        _STUBBED_BY_THIS_FILE.append(_mod)

# graph.knowledge_graph needs networkx — never stub it if networkx is real
_need_graph_stub = not _try_real_import("graph.knowledge_graph")
if _need_graph_stub and "graph.knowledge_graph" not in sys.modules:
    sys.modules["graph.knowledge_graph"] = MagicMock()
    _STUBBED_BY_THIS_FILE.append("graph.knowledge_graph")


@pytest.fixture(autouse=True, scope="module")
def _restore_stubs():
    """Remove module-level stubs after this test module finishes."""
    yield
    # Remove stubs we installed (heavy deps and conditional module stubs)
    for _mod in _STUBBED_BY_THIS_FILE + _HEAVY_DEPS_STUBBED:
        sys.modules.pop(_mod, None)
    # Evict the router so later tests re-import it cleanly
    sys.modules.pop("orchestrator.router", None)
    for _mod in list(sys.modules):
        if "graph.knowledge_graph" in _mod or "retrieval" in _mod:
            sys.modules.pop(_mod, None)

# ── Router Fixture (Guards against sys.modules pollution) ─────────────────────

@pytest.fixture
def router():
    """
    Ensure orchestrator.router is the real module and return it.
    Fixes issue where other tests stub router as MagicMock and xdist workers 
    share sys.modules.
    """
    existing = sys.modules.get("orchestrator.router")
    if existing is None or isinstance(existing, MagicMock):
        sys.modules.pop("orchestrator.router", None)
        import orchestrator.router as router_mod
        import importlib
        importlib.reload(router_mod)
    else:
        import orchestrator.router as router_mod
    
    return router_mod


# ── fallback chain ────────────────────────────────────────────────────────────

def test_fallback_from_anthropic_to_gemini(router):
    """If anthropic fails with a retryable error, falls back to gemini."""
    gemini_response = ModelResponse(
        text="gemini answer", model="gemini-2.0-flash", provider="gemini"
    )

    with (
        patch.object(router, "_available_providers", return_value=["anthropic", "gemini"]),
        patch.object(router, "_call_adapter") as mock_call,
    ):
        mock_call.side_effect = [
            ModelCallError("anthropic", 429, "quota"),
            gemini_response,
        ]
        result = router._dispatch_with_fallback(
            query="test",
            primary_provider="anthropic",
            primary_model="claude-haiku-4-5",
            system_prompt="",
            tool_manifest=[],
            max_tokens=256,
        )

    assert result.text == "gemini answer"
    assert mock_call.call_count == 2


def test_all_providers_fail_raises(router):
    """If all providers fail, raises ModelCallError."""
    with (
        patch.object(router, "_available_providers", return_value=["anthropic"]),
        patch.object(
            router, "_call_adapter",
            side_effect=ModelCallError("anthropic", 429, "all fail"),
        ),
    ):
        with pytest.raises(ModelCallError):
            router._dispatch_with_fallback(
                query="test",
                primary_provider="anthropic",
                primary_model="claude-haiku-4-5",
                system_prompt="",
                tool_manifest=[],
                max_tokens=256,
            )


def test_non_retryable_error_does_not_try_fallback(router):
    """A 401 (auth) error should NOT trigger fallback (non-retryable)."""
    call_count = 0

    def _raise_401(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise ModelCallError("anthropic", 401, "Unauthorized")

    with (
        patch.object(router, "_available_providers", return_value=["anthropic", "gemini"]),
        patch.object(router, "_call_adapter", side_effect=_raise_401),
    ):
        with pytest.raises(ModelCallError):
            router._dispatch_with_fallback(
                query="test",
                primary_provider="anthropic",
                primary_model="claude-haiku-4-5",
                system_prompt="",
                tool_manifest=[],
                max_tokens=256,
            )

    assert call_count == 1  # only one attempt, no fallback


def test_local_primary_with_no_api_keys_calls_adapter_once(router):
    """When primary=local and no API keys are configured, _dispatch_with_fallback
    falls back to calling _call_adapter with local as the only option."""
    standard_response = ModelResponse(
        text="promoted answer", model="claude-haiku-4-5", provider="anthropic"
    )

    with (
        patch.object(router, "_available_providers", return_value=[]),
        patch.object(router, "_call_adapter", return_value=standard_response) as mock_call,
    ):
        result = router._dispatch_with_fallback(
            query="test",
            primary_provider="local",
            primary_model="local-resolver",
            system_prompt="",
            tool_manifest=[],
            max_tokens=256,
        )

    assert result.text == "promoted answer"
    assert mock_call.call_count == 1


def test_available_providers_lists_configured_keys(router, monkeypatch):
    """_available_providers() returns only providers with API keys set."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROK_API_KEY", raising=False)

    providers = router._available_providers()
    assert "anthropic" in providers
    assert "gemini" not in providers
