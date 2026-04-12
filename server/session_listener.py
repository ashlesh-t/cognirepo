# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Session-end hook — fires when an MCP session ends (stdin EOF) or when a
prior unclosed session is detected at the start of the next session.

On session end:
1. Reads the session's tool-call log from .cognirepo/sessions/<id>.json
2. Extracts the top-3 key text arguments from store_memory / log_episode calls
   (heuristic: longest texts + correction-signal texts)
3. Stores each as an auto_summary learning in the project scope
4. Marks the session as closed (closed_at field)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from memory.learning_store import auto_tag, get_learning_store

logger = logging.getLogger(__name__)

_MAX_AUTO_SUMMARY = 3
_CORRECTION_SIGNALS = {"mistake", "fix", "correction", "fixed", "wrong", "don't do", "incorrect"}


def _session_path(session_id: str) -> Optional[Path]:
    try:
        from config.paths import get_path  # pylint: disable=import-outside-toplevel
        return Path(get_path("sessions")) / f"{session_id}.json"
    except Exception:  # pylint: disable=broad-except
        return None


def _load_session(session_id: str) -> Optional[dict]:
    path = _session_path(session_id)
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_session(session_id: str, data: dict) -> None:
    path = _session_path(session_id)
    if path is None:
        return
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        logger.warning("session_listener: could not save session %s: %s", session_id, exc)


def _has_correction_signal(text: str) -> bool:
    lower = text.lower()
    return any(sig in lower for sig in _CORRECTION_SIGNALS)


def _extract_key_texts(session: dict) -> list[str]:
    """
    Heuristic: find the most significant text arguments from the session.
    Prioritises correction-signal texts, then longest texts.
    """
    messages = session.get("messages", [])
    candidates: list[str] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and len(content) > 40:
            candidates.append(content)

    # Sort: correction signals first, then by length
    correction = [t for t in candidates if _has_correction_signal(t)]
    rest = [t for t in candidates if not _has_correction_signal(t)]
    rest.sort(key=len, reverse=True)

    combined = correction + rest
    return combined[:_MAX_AUTO_SUMMARY]


def on_session_end(session_id: str, source_model: str = "") -> None:
    """
    Called when an MCP session ends.  Summarises the session into learnings
    and marks the session as closed.
    """
    session = _load_session(session_id)
    if session is None:
        logger.debug("session_listener: session %s not found", session_id)
        return

    if session.get("closed_at"):
        logger.debug("session_listener: session %s already closed", session_id)
        return

    key_texts = _extract_key_texts(session)
    store = get_learning_store()

    for text in key_texts:
        learning_type, scope = auto_tag(text)
        if learning_type is None:
            # Store as generic decision if the text is substantial
            if len(text) > 100:
                learning_type = "decision"
                scope = "project"
            else:
                continue
        try:
            store.store_learning(
                learning_type,
                text,
                metadata={
                    "source": f"auto_summary:{session_id}",
                    "source_model": source_model,
                    "session_id": session_id,
                },
                scope=scope or "project",
            )
            logger.info(
                "session_listener.learning_stored",
                extra={"session_id": session_id, "type": learning_type},
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("session_listener: store failed: %s", exc)

    # Mark closed
    session["closed_at"] = datetime.now(tz=timezone.utc).isoformat()
    _save_session(session_id, session)
    logger.info("session_listener: session %s closed", session_id)


def recover_unclosed_sessions() -> int:
    """
    Called at MCP session start.  Finds any sessions missing closed_at and
    runs on_session_end() for each.  Returns count of recovered sessions.
    """
    try:
        from config.paths import get_path  # pylint: disable=import-outside-toplevel
        sessions_dir = Path(get_path("sessions"))
    except Exception:  # pylint: disable=broad-except
        return 0

    if not sessions_dir.exists():
        return 0

    count = 0
    for path in sessions_dir.glob("*.json"):
        if path.name == "current.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not data.get("closed_at") and data.get("session_id"):
                logger.info(
                    "session_listener: recovering unclosed session %s",
                    data["session_id"],
                )
                on_session_end(data["session_id"])
                count += 1
        except Exception:  # pylint: disable=broad-except
            pass
    return count
