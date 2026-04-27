# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Claude Code UserPromptSubmit hook — records the user's query into the CogniRepo
behaviour tracker so future get_user_profile() calls include this session's
interaction patterns.

Also prints a compact framing hint to stdout so Claude receives it as
additional system context before responding.

Invoked by Claude Code as:
  python tools/behaviour_hook.py <project_dir>

Stdin: JSON with at least {"prompt": "...", "session_id": "..."} (Claude Code format)
Exit 0: hook succeeded, framing hint printed to stdout
Exit 1: non-blocking error (Claude Code continues regardless)
"""
from __future__ import annotations

import json
import os
import sys


def _load_profile(project_dir: str) -> dict | None:
    """Load user profile from behaviour tracker without starting the MCP server."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from config.paths import set_cognirepo_dir, get_cognirepo_dir_for_repo
        cog_dir = get_cognirepo_dir_for_repo(project_dir)
        set_cognirepo_dir(cog_dir)
        from graph.knowledge_graph import KnowledgeGraph
        from graph.behaviour_tracker import BehaviourTracker
        bt = BehaviourTracker(KnowledgeGraph())
        return bt.get_user_profile()
    except Exception:  # pylint: disable=broad-except
        return None


def _record_query(project_dir: str, query_text: str) -> None:
    """Record query text to behaviour tracker for profile building."""
    try:
        from config.paths import set_cognirepo_dir, get_cognirepo_dir_for_repo
        cog_dir = get_cognirepo_dir_for_repo(project_dir)
        set_cognirepo_dir(cog_dir)
        from graph.knowledge_graph import KnowledgeGraph
        from graph.behaviour_tracker import BehaviourTracker
        bt = BehaviourTracker(KnowledgeGraph())
        bt.record_query(
            query_id=str(abs(hash(query_text + str(os.getpid())))),
            query_text=query_text,
            retrieved_symbols=[],
            faiss_rows=None,
        )
        bt.save()
    except Exception:  # pylint: disable=broad-except
        pass


def main() -> int:
    project_dir = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()

    # Parse stdin — Claude Code sends JSON
    query_text = ""
    try:
        raw = sys.stdin.read()
        if raw.strip():
            data = json.loads(raw)
            # Hook format: {"prompt": "...", "session_id": "..."}
            query_text = data.get("prompt", "") or data.get("message", "") or str(data)
    except (json.JSONDecodeError, OSError):
        pass

    if not query_text:
        return 0

    # Record query to behaviour tracker (best-effort)
    _record_query(project_dir, query_text)

    # Load profile and emit framing hint as additional context
    profile = _load_profile(project_dir)
    if profile and profile.get("framing_hints") and profile["framing_hints"] != "no profile yet":
        total = profile.get("total_queries_tracked", 0)
        if total >= 2:  # emit after 2 queries — enough for early preference signals
            hint = profile["framing_hints"]
            print(
                f"[CogniRepo behaviour profile] {hint}. "
                f"Adapt responses accordingly. "
                f"If this request conflicts with the user's past pattern, "
                f"ask one short clarifying question before proceeding.",
                flush=True,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
