"""
Anthropic adapter — calls claude-* models via the anthropic SDK.

Converts CogniRepo's ContextBundle + tool manifest into the messages/tools
payload expected by `anthropic.Anthropic().messages.create()`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelResponse:
    text: str
    model: str
    provider: str
    tool_calls: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    raw: Any = None


def call(
    query: str,
    system_prompt: str,
    tool_manifest: list[dict],
    model_id: str = "claude-sonnet-4-6",
    max_tokens: int = 2048,
) -> ModelResponse:
    """
    Send query + context to an Anthropic Claude model.

    Parameters
    ----------
    query         : raw user query string
    system_prompt : assembled context from ContextBundle.to_system_prompt()
    tool_manifest : list of CogniRepo tool schemas (from server/manifest.json)
    model_id      : Anthropic model identifier
    max_tokens    : maximum tokens in response
    """
    try:
        import anthropic  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise ImportError("anthropic package required: pip install anthropic") from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    # Build tools array from manifest (Anthropic format)
    tools = _manifest_to_anthropic_tools(tool_manifest)

    create_kwargs: dict[str, Any] = {
        "model": model_id,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": query}],
    }
    if tools:
        create_kwargs["tools"] = tools

    response = client.messages.create(**create_kwargs)

    # Extract text and tool_use blocks
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append({
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })

    usage = {}
    if hasattr(response, "usage"):
        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }

    return ModelResponse(
        text="\n".join(text_parts),
        model=model_id,
        provider="anthropic",
        tool_calls=tool_calls,
        usage=usage,
        raw=response,
    )


def _manifest_to_anthropic_tools(manifest: list[dict]) -> list[dict]:
    """Convert CogniRepo manifest entries to Anthropic tool definitions."""
    tools = []
    for entry in manifest:
        name = entry.get("name", "")
        description = entry.get("description", "")
        parameters = entry.get("parameters", entry.get("inputSchema", {}))
        if not name:
            continue
        tools.append({
            "name": name,
            "description": description,
            "input_schema": parameters if parameters else {"type": "object", "properties": {}},
        })
    return tools
