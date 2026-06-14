# pylint: disable=duplicate-code
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
OpenAI-compatible adapter — works with OpenAI, Azure OpenAI, Ollama, LM Studio,
Cursor, grok (via x.ai), or any endpoint that accepts the OpenAI Chat Completions format.

Environment variables
---------------------
OPENAI_API_KEY      : API key (required for openai.com; can be "ollama" for local)
OPENAI_BASE_URL     : Override base URL (e.g. http://localhost:11434/v1 for Ollama)

The private ``_api_key`` and ``_base_url`` parameters let callers (e.g.
:mod:`grok_adapter`) pass credentials directly without touching env vars.

Wraps every API call with exponential-backoff retry via :mod:`retry`.

Streaming
---------
When ``stream=True``, :func:`call` returns a generator that yields ``str``
text chunks from the streaming Chat Completions response.  The generator's
``StopIteration.value`` carries usage metadata if the endpoint includes it
in the final chunk (requires ``stream_options={"include_usage": True}``).
"""
from __future__ import annotations

import json
import os
from typing import Any, Generator, Union

from orchestrator.model_adapters.anthropic_adapter import ModelResponse
from orchestrator.model_adapters.errors import ModelCallError
from orchestrator.model_adapters.retry import with_retry


def call(
    query: str,
    system_prompt: str,
    tool_manifest: list[dict],
    model_id: str = "gpt-4o",
    max_tokens: int = 2048,
    verbose: bool = False,
    stream: bool = False,
    _api_key: str | None = None,
    _base_url: str | None = None,
    _provider: str = "openai",
    messages_history: list[dict] | None = None,
) -> Union[ModelResponse, Generator[str, None, dict]]:
    """
    Send query + context to an OpenAI-compatible endpoint.
    """
    # pylint: disable=too-many-locals
    try:
        from openai import OpenAI  # pylint: disable=import-outside-toplevel
        from openai import RateLimitError, AuthenticationError  # pylint: disable=import-outside-toplevel
        from openai import APIStatusError, APIConnectionError  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise ImportError("openai package required: pip install openai") from exc

    api_key = _api_key if _api_key is not None else os.environ.get(
        "OPENAI_API_KEY", "sk-placeholder"
    )
    base_url = _base_url if _base_url is not None else os.environ.get("OPENAI_BASE_URL")

    client_kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)

    # Build messages: system prompt first, then history, then current query
    messages = [{"role": "system", "content": system_prompt}]
    if messages_history:
        messages.extend(messages_history)
    messages.append({"role": "user", "content": query})
    tools = _manifest_to_openai_tools(tool_manifest)

    create_kwargs: dict[str, Any] = {
        "model": model_id,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if tools:
        create_kwargs["tools"] = tools
        create_kwargs["tool_choice"] = "auto"

    if stream:
        return _stream_call(
            client, create_kwargs, _provider,
            RateLimitError, AuthenticationError, APIStatusError, APIConnectionError,
        )

    # ── non-streaming path (with retry) ─────────────────────────────────────
    def _do_call():
        try:
            return client.chat.completions.create(**create_kwargs)
        except RateLimitError as exc:
            raise ModelCallError(_provider, 429, str(exc)) from exc
        except AuthenticationError as exc:
            raise ModelCallError(_provider, 401, str(exc)) from exc
        except APIStatusError as exc:
            raise ModelCallError(_provider, exc.status_code, str(exc)) from exc
        except APIConnectionError as exc:
            raise ModelCallError(_provider, None, str(exc)) from exc

    response = with_retry(_do_call, provider=_provider, verbose=verbose)

    choice = response.choices[0]
    message = choice.message
    text = message.content or ""
    tool_calls: list[dict] = []
    if message.tool_calls:
        for tc in message.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, AttributeError):
                args = {}
            tool_calls.append({
                "id": tc.id,
                "name": tc.function.name,
                "arguments": args,
            })

    usage: dict = {}
    if hasattr(response, "usage") and response.usage:
        usage = {
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
        }

    return ModelResponse(
        text=text,
        model=model_id,
        provider=_provider,
        tool_calls=tool_calls,
        usage=usage,
        raw=response,
    )


def _stream_call(
    client,
    create_kwargs: dict,
    provider: str,
    rate_limit_err,
    auth_err,
    status_err,
    conn_err,
) -> Generator[str, None, dict]:
    """
    Generator: yields text delta strings from streaming Chat Completions.
    Returns (via StopIteration.value) a usage dict.

    Requests ``include_usage`` in stream_options so the final chunk carries
    token counts (supported by openai.com; silently ignored by other endpoints).
    """
    usage: dict = {}
    streaming_kwargs = dict(create_kwargs)
    streaming_kwargs["stream"] = True
    streaming_kwargs["stream_options"] = {"include_usage": True}

    try:
        stream = client.chat.completions.create(**streaming_kwargs)
        for chunk in stream:
            # Extract text delta
            try:
                delta = chunk.choices[0].delta
                content = delta.content or ""
            except (AttributeError, IndexError):
                content = ""
            if content:
                yield content
            # Capture usage from the final chunk (if included)
            try:
                if chunk.usage:
                    usage = {
                        "input_tokens": chunk.usage.prompt_tokens or 0,
                        "output_tokens": chunk.usage.completion_tokens or 0,
                    }
            except AttributeError:
                pass
    except rate_limit_err as exc:
        raise ModelCallError(provider, 429, str(exc)) from exc
    except auth_err as exc:
        raise ModelCallError(provider, 401, str(exc)) from exc
    except status_err as exc:
        raise ModelCallError(provider, exc.status_code, str(exc)) from exc
    except conn_err as exc:
        raise ModelCallError(provider, None, str(exc)) from exc

    return usage  # becomes StopIteration.value


def _manifest_to_openai_tools(manifest: list[dict]) -> list[dict]:
    """Convert CogniRepo manifest entries to OpenAI tool definitions."""
    tools = []
    for entry in manifest:
        name = entry.get("name", "")
        description = entry.get("description", "")
        parameters = entry.get("parameters", entry.get("inputSchema", {}))
        if not name:
            continue
        tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters if isinstance(parameters, dict) else {
                    "type": "object",
                    "properties": {},
                },
            },
        })
    return tools
