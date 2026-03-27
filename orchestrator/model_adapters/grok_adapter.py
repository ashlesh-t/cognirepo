# SPDX-FileCopyrightText: 2026 Ashlesh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/your-username/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Grok adapter — thin wrapper over :mod:`openai_adapter` using the x.ai endpoint.

Environment variables
---------------------
GROK_API_KEY : API key from console.x.ai (required)

The x.ai endpoint is OpenAI Chat Completions-compatible, so we delegate
all the heavy lifting to openai_adapter and just swap credentials/URL.
"""
from __future__ import annotations

import os

from orchestrator.model_adapters.anthropic_adapter import ModelResponse
from orchestrator.model_adapters import openai_adapter

_GROK_BASE_URL = "https://api.x.ai/v1"
_DEFAULT_MODEL = "grok-beta"


def call(
    query: str,
    system_prompt: str,
    tool_manifest: list[dict],
    model_id: str = _DEFAULT_MODEL,
    max_tokens: int = 2048,
    verbose: bool = False,
    stream: bool = False,
    messages_history: list[dict] | None = None,
):
    """
    Send query + context to a Grok model via the x.ai OpenAI-compatible API.

    Parameters
    ----------
    query         : raw user query string
    system_prompt : assembled context from ContextBundle.to_system_prompt()
    tool_manifest : list of CogniRepo tool schemas (from server/manifest.json)
    model_id      : Grok model identifier (default: grok-beta)
    max_tokens    : maximum output tokens
    verbose       : if True, print retry messages (passed from CLI --verbose)
    stream        : if True, return a generator that yields text chunks
    """
    api_key = os.environ.get("GROK_API_KEY", "")
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
        _base_url=_GROK_BASE_URL,
        _provider="grok",
    )
