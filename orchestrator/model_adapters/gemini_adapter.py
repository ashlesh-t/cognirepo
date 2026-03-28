# pylint: disable=duplicate-code
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Gemini adapter — calls gemini-* models via google-genai SDK (v1+).

Uses the new Client-based API:
    client = genai.Client(api_key=...)
    client.models.generate_content(model=..., contents=..., config=...)

Wraps every API call with exponential-backoff retry via :mod:`retry`.

Streaming
---------
When ``stream=True``, :func:`call` returns a generator that yields ``str``
text chunks.  Uses ``client.models.generate_content_stream()`` (falls back
to a single-chunk generator if the method is unavailable in the installed
version).  The generator's ``StopIteration.value`` carries usage metadata.
"""
from __future__ import annotations

import os
from typing import Any, Generator, Union

from orchestrator.model_adapters.anthropic_adapter import ModelResponse
from orchestrator.model_adapters.errors import ModelCallError
from orchestrator.model_adapters.retry import with_retry


def call(
    query: str,
    system_prompt: str,
    tool_manifest: list[dict],
    model_id: str = "gemini-2.0-flash",
    max_tokens: int = 2048,
    verbose: bool = False,
    stream: bool = False,
    messages_history: list[dict] | None = None,
) -> Union[ModelResponse, Generator[str, None, dict]]:
    """
    Send query + context to a Gemini model.
    """
    # pylint: disable=too-many-locals
    try:
        from google import genai  # pylint: disable=import-outside-toplevel
        from google.genai import types as genai_types  # pylint: disable=import-outside-toplevel
        from google.genai import errors as genai_errors  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise ImportError(
            "google-genai package required: pip install google-genai"
        ) from exc

    api_key = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))
    client = genai.Client(api_key=api_key) if api_key else genai.Client()

    config_kwargs: dict[str, Any] = {
        "system_instruction": system_prompt,
        "max_output_tokens": max_tokens,
    }
    tool_list = _manifest_to_tools(tool_manifest, genai_types)
    if tool_list:
        config_kwargs["tools"] = tool_list
    config = genai_types.GenerateContentConfig(**config_kwargs)

    # Build Gemini contents (string for single-turn, list for multi-turn)
    contents = _build_contents(query, messages_history)

    if stream:
        return _stream_call(client, model_id, contents, config, genai_errors)

    # ── non-streaming path (with retry) ─────────────────────────────────────
    def _do_call():
        try:
            return client.models.generate_content(
                model=model_id,
                contents=contents,
                config=config,
            )
        except genai_errors.ClientError as exc:
            code = _extract_code(exc, default=400)
            raise ModelCallError("gemini", code, str(exc)) from exc
        except genai_errors.ServerError as exc:
            code = _extract_code(exc, default=500)
            raise ModelCallError("gemini", code, str(exc)) from exc
        except genai_errors.APIError as exc:
            code = _extract_code(exc, default=500)
            raise ModelCallError("gemini", code, str(exc)) from exc

    response = with_retry(_do_call, provider="gemini", verbose=verbose)

    text_parts: list[str] = []
    tool_calls: list[dict] = []

    try:
        for candidate in response.candidates:
            for part in candidate.content.parts:
                if hasattr(part, "text") and part.text:
                    text_parts.append(part.text)
                elif hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    tool_calls.append({
                        "name": fc.name,
                        "args": dict(fc.args) if fc.args else {},
                    })
    except (AttributeError, IndexError):
        try:
            text_parts.append(response.text or "")
        except (AttributeError, ValueError):
            text_parts.append("")

    usage: dict = {}
    try:
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            usage = {
                "input_tokens": response.usage_metadata.prompt_token_count or 0,
                "output_tokens": response.usage_metadata.candidates_token_count or 0,
            }
    except AttributeError:
        pass

    return ModelResponse(
        text="\n".join(text_parts),
        model=model_id,
        provider="gemini",
        tool_calls=tool_calls,
        usage=usage,
        raw=response,
    )


def _build_contents(query: str, messages_history: list[dict] | None):
    """
    Build Gemini ``contents`` from conversation history + current query.

    Single-turn (no history): returns a plain string (Gemini handles it natively).
    Multi-turn (with history): returns a list of role/parts dicts, converting
    ``"assistant"`` → ``"model"`` as Gemini requires.
    """
    if not messages_history:
        return query  # simple string for single-turn

    contents = []
    for msg in messages_history:
        role = "model" if msg["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    contents.append({"role": "user", "parts": [{"text": query}]})
    return contents


def _stream_call(
    client,
    model_id: str,
    contents,           # str or list[dict] — result of _build_contents()
    config,
    genai_errors,
) -> Generator[str, None, dict]:
    """
    Generator: yields text chunk strings from Gemini streaming API.
    Returns (via StopIteration.value) a usage dict.
    """
    usage: dict = {}

    # Use generate_content_stream if available; fall back to blocking call
    stream_fn = getattr(client.models, "generate_content_stream", None)
    if stream_fn is None:
        # Fallback: call blocking and yield the full text as one chunk
        try:
            response = client.models.generate_content(
                model=model_id, contents=contents, config=config
            )
            text = getattr(response, "text", "") or ""
            if text:
                yield text
            try:
                if response.usage_metadata:
                    usage = {
                        "input_tokens": response.usage_metadata.prompt_token_count or 0,
                        "output_tokens": response.usage_metadata.candidates_token_count or 0,
                    }
            except AttributeError:
                pass
        except genai_errors.APIError as exc:
            code = _extract_code(exc, default=500)
            raise ModelCallError("gemini", code, str(exc)) from exc
        return usage

    try:
        for chunk in stream_fn(model=model_id, contents=contents, config=config):
            # Extract text from chunk
            chunk_text = ""
            try:
                chunk_text = chunk.text or ""
            except (AttributeError, ValueError):
                try:
                    for cand in chunk.candidates:
                        for part in cand.content.parts:
                            if hasattr(part, "text") and part.text:
                                chunk_text += part.text
                except (AttributeError, IndexError):
                    pass
            if chunk_text:
                yield chunk_text
            # Try to capture usage from each chunk (last one wins)
            try:
                if chunk.usage_metadata:
                    usage = {
                        "input_tokens": chunk.usage_metadata.prompt_token_count or 0,
                        "output_tokens": chunk.usage_metadata.candidates_token_count or 0,
                    }
            except AttributeError:
                pass
    except genai_errors.ClientError as exc:
        raise ModelCallError("gemini", _extract_code(exc, 400), str(exc)) from exc
    except genai_errors.ServerError as exc:
        raise ModelCallError("gemini", _extract_code(exc, 500), str(exc)) from exc
    except genai_errors.APIError as exc:
        raise ModelCallError("gemini", _extract_code(exc, 500), str(exc)) from exc

    return usage  # becomes StopIteration.value


def _extract_code(exc: Exception, default: int) -> int:
    """Extract HTTP status code from a google-genai error."""
    for attr in ("code", "status_code", "http_code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    msg = str(exc)
    for candidate in ("429", "500", "503", "400", "401", "404"):
        if candidate in msg:
            return int(candidate)
    return default


def _manifest_to_tools(manifest: list[dict], genai_types) -> list:
    """Convert CogniRepo manifest entries to google-genai Tool objects."""
    declarations = []
    for entry in manifest:
        name = entry.get("name", "")
        description = entry.get("description", "")
        parameters = entry.get("parameters", entry.get("inputSchema", {}))
        if not name:
            continue
        try:
            schema = _dict_to_schema(parameters, genai_types) if parameters else None
            fd_kwargs: dict[str, Any] = {"name": name, "description": description}
            if schema is not None:
                fd_kwargs["parameters"] = schema
            declarations.append(genai_types.FunctionDeclaration(**fd_kwargs))
        except Exception:  # pylint: disable=broad-except
            continue

    if not declarations:
        return []
    return [genai_types.Tool(function_declarations=declarations)]


def _dict_to_schema(schema: dict, genai_types):
    """Recursively convert a JSON Schema dict to a google-genai Schema."""
    type_map = {
        "string": "STRING",
        "number": "NUMBER",
        "integer": "INTEGER",
        "boolean": "BOOLEAN",
        "array": "ARRAY",
        "object": "OBJECT",
    }
    gtype = type_map.get(schema.get("type", "object"), "OBJECT")
    props = {}
    for k, v in schema.get("properties", {}).items():
        props[k] = _dict_to_schema(v, genai_types)
    kwargs: dict[str, Any] = {
        "type": gtype,
        "description": schema.get("description", ""),
    }
    if props:
        kwargs["properties"] = props
    required = schema.get("required", [])
    if required:
        kwargs["required"] = required
    return genai_types.Schema(**kwargs)
