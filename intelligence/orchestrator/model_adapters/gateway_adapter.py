# pylint: disable=duplicate-code
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Gateway adapter — thin wrapper over :mod:`openai_adapter` for any OpenAI-compatible gateway (LiteLLM, OpenRouter,
aicredits.in, a local proxy, ...): one URL and one key in front of many models.

Environment variables
---------------------
COGNIREPO_GATEWAY_BASE_URL : gateway base URL, e.g. ``https://host/v1`` (required; see :mod:`intelligence.orchestrator.gateway`)
COGNIREPO_GATEWAY_API_KEY  : gateway key (required)

There is no default model: a gateway's catalogue is its own, so the caller must pass one (the router resolves it from
``model_overrides.pin.gateway`` or a discovered model under ``gateway.prefer``).
"""
from __future__ import annotations

from intelligence.orchestrator import gateway
from intelligence.orchestrator.model_adapters import openai_adapter
from intelligence.orchestrator.model_adapters.errors import ModelCallError


def call(
    query: str,
    system_prompt: str,
    tool_manifest: list[dict],
    model_id: str = "",
    max_tokens: int = 2048,
    verbose: bool = False,
    stream: bool = False,
    messages_history: list[dict] | None = None,
):
    """
    Send query + context to a model on the configured gateway.

    Parameters
    ----------
    query         : raw user query string
    system_prompt : assembled context from ContextBundle.to_system_prompt()
    tool_manifest : list of CogniRepo tool schemas (from server/manifest.json)
    model_id      : the gateway's own id for the model, e.g. ``vendor/model`` (required)
    max_tokens    : maximum output tokens
    verbose       : if True, print retry messages (passed from CLI --verbose)
    stream        : if True, return a generator that yields text chunks
    """
    base_url, api_key = gateway.base_url(), gateway.api_key()
    if base_url is None or not api_key:
        raise ModelCallError(
            "gateway", None,
            f"no usable gateway: set {gateway.ENV_URL} (https URL) and {gateway.ENV_KEY}",
        )
    if not model_id:
        raise ModelCallError(
            "gateway", None,
            "no model chosen for the gateway: pin one under model_overrides.pin.gateway "
            f"or set {gateway.ENV_PREFER} (an id prefix) and run `cognirepo models refresh`",
        )
    return openai_adapter.call(
        query=query,
        system_prompt=system_prompt,
        tool_manifest=tool_manifest,
        model_id=model_id,
        max_tokens=max_tokens,
        verbose=verbose,
        stream=stream,
        messages_history=messages_history,
        _api_key=api_key,
        _base_url=base_url,
        _provider="gateway",
    )
