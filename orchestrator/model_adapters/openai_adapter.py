"""
OpenAI-compatible adapter — works with OpenAI, Azure OpenAI, Ollama, LM Studio,
Cursor, or any endpoint that accepts the OpenAI Chat Completions format.

Environment variables
---------------------
OPENAI_API_KEY      : API key (required for openai.com; can be "ollama" for local)
OPENAI_BASE_URL     : Override base URL (e.g. http://localhost:11434/v1 for Ollama)
"""
from __future__ import annotations

import os
from typing import Any

from orchestrator.model_adapters.anthropic_adapter import ModelResponse


def call(
    query: str,
    system_prompt: str,
    tool_manifest: list[dict],
    model_id: str = "gpt-4o",
    max_tokens: int = 2048,
) -> ModelResponse:
    """
    Send query + context to an OpenAI-compatible endpoint.

    Parameters
    ----------
    query         : raw user query string
    system_prompt : assembled context from ContextBundle.to_system_prompt()
    tool_manifest : list of CogniRepo tool schemas (from server/manifest.json)
    model_id      : model identifier (e.g. "gpt-4o", "gpt-3.5-turbo", "mistral")
    max_tokens    : maximum tokens in response
    """
    try:
        from openai import OpenAI  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise ImportError("openai package required: pip install openai") from exc

    api_key = os.environ.get("OPENAI_API_KEY", "sk-placeholder")
    base_url = os.environ.get("OPENAI_BASE_URL")

    client_kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]

    # Build tools array from manifest (OpenAI format)
    tools = _manifest_to_openai_tools(tool_manifest)

    create_kwargs: dict[str, Any] = {
        "model": model_id,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if tools:
        create_kwargs["tools"] = tools
        create_kwargs["tool_choice"] = "auto"

    response = client.chat.completions.create(**create_kwargs)

    choice = response.choices[0]
    message = choice.message

    text = message.content or ""
    tool_calls: list[dict] = []
    if message.tool_calls:
        for tc in message.tool_calls:
            import json  # pylint: disable=import-outside-toplevel
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
        provider="openai",
        tool_calls=tool_calls,
        usage=usage,
        raw=response,
    )


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
