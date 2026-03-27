"""
Anthropic adapter — calls claude-* models via the anthropic SDK.

Converts CogniRepo's ContextBundle + tool manifest into the messages/tools
payload expected by `anthropic.Anthropic().messages.create()`.

Wraps every API call with exponential-backoff retry via :mod:`retry`.

Streaming
---------
When ``stream=True``, :func:`call` returns a *generator* that yields ``str``
text chunks as they arrive.  The generator's ``StopIteration.value`` carries
``{"input_tokens": N, "output_tokens": M}`` usage metadata pulled from the
final Anthropic message.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Generator, Union

from orchestrator.model_adapters.errors import ModelCallError
from orchestrator.model_adapters.retry import with_retry


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
    verbose: bool = False,
    stream: bool = False,
    messages_history: list[dict] | None = None,
) -> Union[ModelResponse, Generator[str, None, dict]]:
    """
    Send query + context to an Anthropic Claude model.

    Parameters
    ----------
    query         : raw user query string
    system_prompt : assembled context from ContextBundle.to_system_prompt()
    tool_manifest : list of CogniRepo tool schemas (from server/manifest.json)
    model_id      : Anthropic model identifier
    max_tokens    : maximum tokens in response
    verbose       : if True, print retry messages (passed from CLI --verbose)
    stream        : if True, return a generator that yields text chunks;
                    the generator's StopIteration.value is a usage dict
    """
    try:
        import anthropic  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise ImportError("anthropic package required: pip install anthropic") from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    tools = _manifest_to_anthropic_tools(tool_manifest)

    # Build messages: prepend conversation history, then current query
    messages: list[dict] = []
    if messages_history:
        messages.extend(messages_history)
    messages.append({"role": "user", "content": query})

    create_kwargs: dict[str, Any] = {
        "model": model_id,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": messages,
    }
    if tools:
        create_kwargs["tools"] = tools

    if stream:
        return _stream_call(client, create_kwargs, model_id, anthropic)

    # ── non-streaming path (with retry) ─────────────────────────────────────
    def _do_call():
        try:
            return client.messages.create(**create_kwargs)
        except anthropic.RateLimitError as exc:
            raise ModelCallError("anthropic", 429, str(exc)) from exc
        except anthropic.AuthenticationError as exc:
            raise ModelCallError("anthropic", 401, str(exc)) from exc
        except anthropic.BadRequestError as exc:
            raise ModelCallError("anthropic", 400, str(exc)) from exc
        except anthropic.APIStatusError as exc:
            raise ModelCallError("anthropic", exc.status_code, str(exc)) from exc

    response = with_retry(_do_call, provider="anthropic", verbose=verbose)

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


def _stream_call(
    client,
    create_kwargs: dict,
    model_id: str,
    anthropic_mod,
) -> Generator[str, None, dict]:
    """
    Generator: yields text delta strings as they arrive from the Anthropic
    streaming API.  Returns (via StopIteration.value) a usage dict.
    """
    usage: dict = {}
    try:
        with client.messages.stream(**create_kwargs) as stream:
            for text in stream.text_stream:
                yield text
            # Collect usage from the completed message
            try:
                final_msg = stream.get_final_message()
                usage = {
                    "input_tokens": final_msg.usage.input_tokens,
                    "output_tokens": final_msg.usage.output_tokens,
                }
            except Exception:  # pylint: disable=broad-except
                pass
    except anthropic_mod.RateLimitError as exc:
        raise ModelCallError("anthropic", 429, str(exc)) from exc
    except anthropic_mod.AuthenticationError as exc:
        raise ModelCallError("anthropic", 401, str(exc)) from exc
    except anthropic_mod.BadRequestError as exc:
        raise ModelCallError("anthropic", 400, str(exc)) from exc
    except anthropic_mod.APIStatusError as exc:
        raise ModelCallError("anthropic", exc.status_code, str(exc)) from exc
    return usage  # becomes StopIteration.value


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
