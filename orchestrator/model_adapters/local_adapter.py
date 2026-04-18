# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
orchestrator/model_adapters/local_adapter.py — Local (zero-API) resolver adapter.

Handles QUICK-tier queries entirely from the local index:
  1. try_local_resolve() — symbol/file/graph pattern matching
  2. DocsIndex — embedded docs FAISS search (CogniRepo usage questions)

Raises :class:`NoLocalAnswer` when neither source has a confident answer,
signalling the router to promote the query to STANDARD tier.
"""
from __future__ import annotations

import logging
from typing import Generator

from orchestrator.model_adapters.anthropic_adapter import ModelResponse

logger = logging.getLogger(__name__)


class NoLocalAnswer(Exception):
    """Raised when the local adapter has no confident answer for a query."""


def call(
    query: str,
    system_prompt: str = "",
    tool_manifest: list = None,
    model_id: str = "local-resolver",
    max_tokens: int = 0,
    stream: bool = False,
    messages_history: list | None = None,
) -> ModelResponse | Generator[str, None, dict]:
    """
    Attempt to answer the query from local indexes only.

    Parameters
    ----------
    query        : raw user query
    stream       : if True, yields a single chunk (the answer text)
    (other params: accepted for interface compatibility but ignored)

    Returns
    -------
    ModelResponse  (non-streaming)  or  Generator[str, None, dict]  (streaming)

    Raises
    ------
    NoLocalAnswer : if no confident local answer is available
    """
    answer = _resolve_locally(query)
    if answer is None:
        raise NoLocalAnswer(f"No local answer for: {query!r}")

    logger.debug("local_adapter: resolved locally (%d chars)", len(answer))

    if stream:
        return _stream_answer(answer)

    return ModelResponse(
        text=answer,
        model=model_id,
        provider="local",
        usage={"input_tokens": 0, "output_tokens": 0},
    )


def _resolve_locally(query: str) -> str | None:
    """Try all local resolution strategies; return text or None."""
    # ── 1. Pattern-based resolver (symbol/file/graph/history) ────────────────
    try:
        from orchestrator.router import try_local_resolve  # pylint: disable=import-outside-toplevel
        from orchestrator.context_builder import ContextBundle  # pylint: disable=import-outside-toplevel
        bundle = ContextBundle(query=query)
        answer = try_local_resolve(query, bundle)
        if answer is not None:
            return answer
    except Exception:  # pylint: disable=broad-except
        pass

    # ── 2. Docs FAISS index (CogniRepo usage questions) ───────────────────────
    try:
        from cli.docs_index import ensure_docs_index, _CONFIDENCE_THRESHOLD  # pylint: disable=import-outside-toplevel
        idx = ensure_docs_index()
        if idx is not None and idx.is_docs_query(query):
            results = idx.answer(query, top_k=3)
            if results and results[0]["score"] >= _CONFIDENCE_THRESHOLD:
                top = results[0]
                return top["text"] + f"\n\n→ see: {top['file']} § {top['section']}"
    except Exception:  # pylint: disable=broad-except
        pass

    return None


def _stream_answer(text: str) -> Generator[str, None, dict]:
    """Yield the answer as a single chunk (local answers are instant)."""
    yield text
    return {"input_tokens": 0, "output_tokens": len(text.split())}
