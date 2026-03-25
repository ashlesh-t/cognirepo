"""
Gemini adapter — calls gemini-* models via google-generativeai SDK.

Converts CogniRepo's ContextBundle + tool manifest into the contents/tools
payload expected by the GenerativeModel API.
"""
from __future__ import annotations

import os
from typing import Any

from orchestrator.model_adapters.anthropic_adapter import ModelResponse


def call(
    query: str,
    system_prompt: str,
    tool_manifest: list[dict],
    model_id: str = "gemini-2.0-flash",
    max_tokens: int = 2048,
) -> ModelResponse:
    """
    Send query + context to a Gemini model.

    Parameters
    ----------
    query         : raw user query string
    system_prompt : assembled context from ContextBundle.to_system_prompt()
    tool_manifest : list of CogniRepo tool schemas (from server/manifest.json)
    model_id      : Gemini model identifier
    max_tokens    : maximum output tokens
    """
    try:
        import google.generativeai as genai  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise ImportError(
            "google-generativeai package required: pip install google-generativeai"
        ) from exc

    api_key = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))
    if api_key:
        genai.configure(api_key=api_key)

    # Build function declarations from manifest
    function_declarations = _manifest_to_function_declarations(tool_manifest)

    generation_config = genai.GenerationConfig(max_output_tokens=max_tokens)

    model_kwargs: dict[str, Any] = {
        "model_name": model_id,
        "system_instruction": system_prompt,
        "generation_config": generation_config,
    }
    if function_declarations:
        model_kwargs["tools"] = [genai.protos.Tool(function_declarations=function_declarations)]

    model = genai.GenerativeModel(**model_kwargs)
    response = model.generate_content(query)

    # Extract text and function calls
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    usage: dict = {}

    try:
        for candidate in response.candidates:
            for part in candidate.content.parts:
                if hasattr(part, "text") and part.text:
                    text_parts.append(part.text)
                elif hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    tool_calls.append({
                        "name": fc.name,
                        "args": dict(fc.args),
                    })
    except (AttributeError, IndexError):
        # Fallback: try response.text
        try:
            text_parts.append(response.text)
        except ValueError:
            text_parts.append("")

    try:
        if hasattr(response, "usage_metadata"):
            usage = {
                "input_tokens": response.usage_metadata.prompt_token_count,
                "output_tokens": response.usage_metadata.candidates_token_count,
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


def _manifest_to_function_declarations(manifest: list[dict]) -> list:
    """Convert CogniRepo manifest entries to Gemini FunctionDeclaration objects."""
    try:
        import google.generativeai as genai  # pylint: disable=import-outside-toplevel
    except ImportError:
        return []

    declarations = []
    for entry in manifest:
        name = entry.get("name", "")
        description = entry.get("description", "")
        parameters = entry.get("parameters", entry.get("inputSchema", {}))
        if not name:
            continue
        # Gemini expects parameters as a Schema dict
        schema_dict = parameters if isinstance(parameters, dict) else {}
        try:
            fd = genai.protos.FunctionDeclaration(
                name=name,
                description=description,
                parameters=_dict_to_schema(schema_dict),
            )
            declarations.append(fd)
        except Exception:  # pylint: disable=broad-except
            continue
    return declarations


def _dict_to_schema(schema: dict):
    """Recursively convert a JSON Schema dict to a Gemini Schema proto."""
    try:
        import google.generativeai as genai  # pylint: disable=import-outside-toplevel

        type_map = {
            "string": genai.protos.Type.STRING,
            "number": genai.protos.Type.NUMBER,
            "integer": genai.protos.Type.INTEGER,
            "boolean": genai.protos.Type.BOOLEAN,
            "array": genai.protos.Type.ARRAY,
            "object": genai.protos.Type.OBJECT,
        }
        gtype = type_map.get(schema.get("type", "object"), genai.protos.Type.OBJECT)
        props = {}
        for k, v in schema.get("properties", {}).items():
            props[k] = _dict_to_schema(v)
        return genai.protos.Schema(
            type_=gtype,
            description=schema.get("description", ""),
            properties=props,
            required=schema.get("required", []),
        )
    except Exception:  # pylint: disable=broad-except
        return None
