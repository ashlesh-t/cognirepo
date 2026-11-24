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
from intelligence.orchestrator.model_adapters.errors import ModelCallError  # noqa: E402
from intelligence.orchestrator.model_adapters.anthropic_adapter import ModelResponse  # noqa: E402

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
    "intelligence.orchestrator.context_builder",
    "intelligence.orchestrator.model_adapters.gemini_adapter",
    "intelligence.orchestrator.model_adapters.grok_adapter",
    "intelligence.orchestrator.model_adapters.openai_adapter",
    "data.graph.behaviour_tracker",
    "data.memory.episodic_memory",
):
    if _mod not in sys.modules and not _try_real_import(_mod):
        sys.modules[_mod] = MagicMock()
        _STUBBED_BY_THIS_FILE.append(_mod)

# graph.knowledge_graph needs networkx — never stub it if networkx is real
_need_graph_stub = not _try_real_import("data.graph.knowledge_graph")
if _need_graph_stub and "data.graph.knowledge_graph" not in sys.modules:
    sys.modules["data.graph.knowledge_graph"] = MagicMock()
    _STUBBED_BY_THIS_FILE.append("data.graph.knowledge_graph")


@pytest.fixture(autouse=True, scope="module")
def _restore_stubs():
    """Remove module-level stubs after this test module finishes."""
    yield
    # Remove stubs we installed (heavy deps and conditional module stubs)
    for _mod in _STUBBED_BY_THIS_FILE + _HEAVY_DEPS_STUBBED:
        sys.modules.pop(_mod, None)
    # Evict the router so later tests re-import it cleanly
    sys.modules.pop("intelligence.orchestrator.router", None)
    for _mod in list(sys.modules):
        if "data.graph.knowledge_graph" in _mod or "retrieval" in _mod:
            sys.modules.pop(_mod, None)

# ── Router Fixture (Guards against sys.modules pollution) ─────────────────────

@pytest.fixture
def router():
    """
    Ensure orchestrator.router is the real module and return it.
    Fixes issue where other tests stub router as MagicMock and xdist workers 
    share sys.modules.
    """
    existing = sys.modules.get("intelligence.orchestrator.router")
    if existing is None or isinstance(existing, MagicMock):
        sys.modules.pop("intelligence.orchestrator.router", None)
        import intelligence.orchestrator.router as router_mod
        import importlib
        importlib.reload(router_mod)
    else:
        import intelligence.orchestrator.router as router_mod
    
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


# ── gateway: one URL + key in front of many models ────────────────────────────

_PIN_STANDARD = {"model_overrides": {"pin": {"gateway": {"STANDARD": "vendor/pinned-model"}}}}


def _clear_vendor_keys(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "GROK_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def test_gateway_is_available_only_with_a_valid_url_and_a_key(router, monkeypatch):
    _clear_vendor_keys(monkeypatch)
    monkeypatch.setenv("COGNIREPO_GATEWAY_API_KEY", "k")
    assert "gateway" not in router._available_providers()  # key alone: nowhere to send it
    monkeypatch.setenv("COGNIREPO_GATEWAY_BASE_URL", "http://gw.example.test/v1")
    assert "gateway" not in router._available_providers()  # remote plain http is refused
    monkeypatch.setenv("COGNIREPO_GATEWAY_BASE_URL", "https://gw.example.test/v1")
    assert router._available_providers() == ["gateway"]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert router._available_providers() == ["anthropic", "gateway"]  # real vendor keys come first
    monkeypatch.delenv("COGNIREPO_GATEWAY_API_KEY")
    assert router._available_providers() == ["anthropic"]


def test_gateway_without_a_model_is_skipped_never_guessed(router, monkeypatch):
    """No pin and no `prefer`: the gateway has nothing to send, so the chain moves on to the next backend."""
    with (
        patch.object(router, "_available_providers", return_value=["gateway"]),
        patch.object(router, "_cli_backends", return_value=["codex-cli"]),
        patch.object(router, "_load_config", return_value={}),
        patch.object(router, "_call_adapter") as mock_call,
    ):
        mock_call.return_value = ModelResponse(text="from cli", model="", provider="codex-cli")
        result = router._dispatch_with_fallback(
            query="q", primary_provider="anthropic", primary_model="claude-haiku-4-5",
            system_prompt="", tool_manifest=[], max_tokens=64, tier="STANDARD",
        )
    assert result.text == "from cli"
    assert [c.kwargs["provider"] for c in mock_call.call_args_list] == ["codex-cli"]  # the gateway was never called


def test_gateway_alone_without_a_model_fails_with_a_message_that_says_what_to_set(router):
    with (
        patch.object(router, "_available_providers", return_value=["gateway"]),
        patch.object(router, "_cli_backends", return_value=[]),
        patch.object(router, "_load_config", return_value={}),
        patch.object(router, "_call_adapter") as mock_call,
    ):
        with pytest.raises(ModelCallError) as ei:
            router._dispatch_with_fallback(
                query="q", primary_provider="anthropic", primary_model="claude-haiku-4-5",
                system_prompt="", tool_manifest=[], max_tokens=64, tier="STANDARD",
            )
    assert "no model chosen" in ei.value.message and "COGNIREPO_GATEWAY_PREFER" in ei.value.message
    mock_call.assert_not_called()


def test_a_pinned_gateway_model_is_used_and_is_a_fallback_for_a_failing_vendor(router):
    ok = ModelResponse(text="gw answer", model="vendor/pinned-model", provider="gateway")
    with (
        patch.object(router, "_available_providers", return_value=["anthropic", "gateway"]),
        patch.object(router, "_cli_backends", return_value=[]),
        patch.object(router, "_load_config", return_value=_PIN_STANDARD),
        patch.object(router, "_call_adapter") as mock_call,
    ):
        mock_call.side_effect = [ModelCallError("anthropic", 429, "quota"), ok]
        result = router._dispatch_with_fallback(
            query="q", primary_provider="anthropic", primary_model="claude-haiku-4-5",
            system_prompt="", tool_manifest=[], max_tokens=64, tier="STANDARD",
        )
    assert result.text == "gw answer"
    second = mock_call.call_args_list[1].kwargs
    assert second["provider"] == "gateway" and second["model_id"] == "vendor/pinned-model"


def test_usable_backends_drops_only_a_modelless_gateway(router):
    backends = ["anthropic", "gateway", "codex-cli"]
    with patch.object(router, "_load_config", return_value={}):
        assert router._usable_backends(backends, "STANDARD") == ["anthropic", "codex-cli"]
    with patch.object(router, "_load_config", return_value=_PIN_STANDARD):
        assert router._usable_backends(backends, "STANDARD") == backends
        assert router._usable_backends(backends, "EXPERT") == ["anthropic", "codex-cli"]  # pinned for STANDARD only
    assert not router._no_model("codex-cli", "")  # an agent CLI's empty model means "its own default"
    assert router._no_model("gateway", "") and not router._no_model("gateway", "vendor/m")


def test_call_adapter_and_stream_dispatch_reach_the_gateway_adapter(router):
    from intelligence.orchestrator.model_adapters import gateway_adapter
    resp = ModelResponse(text="x", model="m", provider="gateway")
    with patch.object(gateway_adapter, "call", return_value=resp) as call:
        out = router._call_adapter(query="q", provider="gateway", model_id="vendor/m", system_prompt="s",
                                   tool_manifest=[], max_tokens=8)
        assert out is resp and call.call_args.kwargs["model_id"] == "vendor/m"

    def fake_stream(**_kw):
        yield "chunk"
        return {"input_tokens": 1, "output_tokens": 1}

    with patch.object(gateway_adapter, "call", side_effect=fake_stream):
        gen = router._stream_dispatch(query="q", provider="gateway", model_id="vendor/m", system_prompt="s",
                                      tool_manifest=[], max_tokens=8)
        assert next(gen) == "chunk"


def test_a_quick_query_the_local_resolver_cannot_answer_uses_the_standard_pick_on_a_gateway(router):
    """QUICK has no tier of its own on a gateway; a vendor falls back to its cheap default, a gateway to STANDARD."""
    with patch.object(router, "_load_config", return_value=_PIN_STANDARD):
        assert router._model_for("gateway", "QUICK") == "vendor/pinned-model"
        assert router._model_for("gateway", "EXPERT") == ""  # only STANDARD is pinned: no other tier borrows it
    with (
        patch.object(router, "_available_providers", return_value=["gateway"]),
        patch.object(router, "_cli_backends", return_value=[]),
        patch.object(router, "_load_config", return_value=_PIN_STANDARD),
        patch.object(router, "_call_adapter") as mock_call,
    ):
        mock_call.return_value = ModelResponse(text="gw", model="vendor/pinned-model", provider="gateway")
        router._dispatch_with_fallback(
            query="q", primary_provider="local", primary_model="local-resolver",
            system_prompt="", tool_manifest=[], max_tokens=64, tier="QUICK",
        )
    assert mock_call.call_args.kwargs["model_id"] == "vendor/pinned-model"
