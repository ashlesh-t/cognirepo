# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
MCP tool-call interceptor — automatically captures learnings from
store_memory and log_episode calls without any manual steps.

How it works
------------
After every store_memory or log_episode call, auto_tag() is applied to
the text.  If a learning signal is detected, the text is stored in the
appropriate LearningStore scope (project or global).

Usage
-----
Wrap tool call results in `intercept_after_store` / `intercept_after_episode`.
Both are called from server/mcp_server.py after the underlying tool runs.
"""
from __future__ import annotations

import logging

from memory.learning_store import auto_tag, get_learning_store

logger = logging.getLogger(__name__)


def intercept_after_store(
    text: str,
    source: str = "",
    session_id: str = "",
    source_model: str = "",
) -> None:
    """
    Called after every store_memory invocation.
    Extracts and persists a learning if a signal phrase is present.
    """
    learning_type, scope = auto_tag(text)
    if learning_type is None:
        return

    store = get_learning_store()
    metadata = {
        "source": source,
        "source_model": source_model,
        "session_id": session_id,
    }
    try:
        result = store.store_learning(learning_type, text, metadata, scope=scope or "project")
        logger.info(
            "learning.captured",
            extra={
                "type": learning_type,
                "scope": result.get("scope"),
                "id": result.get("id"),
            },
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("learning.capture_failed: %s", exc)


def intercept_after_episode(
    event: str,
    metadata: dict | None = None,
    session_id: str = "",
    source_model: str = "",
) -> None:
    """
    Called after every log_episode invocation.
    Extracts and persists a learning if a signal phrase is present.
    """
    learning_type, scope = auto_tag(event)
    if learning_type is None:
        return

    store = get_learning_store()
    meta = dict(metadata or {})
    meta.update({"source_model": source_model, "session_id": session_id})

    try:
        result = store.store_learning(learning_type, event, meta, scope=scope or "project")
        logger.info(
            "learning.episode_captured",
            extra={
                "type": learning_type,
                "scope": result.get("scope"),
                "id": result.get("id"),
            },
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("learning.episode_capture_failed: %s", exc)
