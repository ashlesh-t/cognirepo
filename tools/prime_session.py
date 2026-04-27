# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tools/prime_session.py — Session bootstrap brief for agent orientation.

Extracted from cli/main.py::_cmd_prime() so MCP tools and the CLI can share
the same implementation without circular imports.
"""
from __future__ import annotations

import datetime
import json
import os

from config.paths import get_path


def prime_session() -> dict:
    """
    Generate a session bootstrap brief.

    Returns architecture summary, entry points (most-called symbols),
    recent decisions from the learning store, hot symbols from the behaviour
    tracker, and index health (symbol count, file count, last_indexed).

    Used by both `cognirepo prime` (CLI) and `get_session_brief` (MCP tool).
    """
    brief: dict = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "repo": os.path.basename(os.getcwd()),
        "architecture": [],
        "entry_points": [],
        "recent_decisions": [],
        "hot_symbols": [],
        "known_blind_spots": [
            "scheduler-registered functions (add_job) require string-literal fallback in who_calls",
            "decorators-only registration (@app.route) may not appear in AST call graph",
        ],
        "index_health": {},
    }

    # ── architecture + recent decisions from learning store ───────────────────
    try:
        from memory.learning_store import get_learning_store  # pylint: disable=import-outside-toplevel
        store = get_learning_store()
        arch_learnings = store.retrieve_learnings("architecture overview design", top_k=3)
        brief["architecture"] = [
            {"text": lr.get("text", "")[:200], "type": lr.get("type", "")}
            for lr in arch_learnings
        ]
        recent = store.retrieve_learnings("decision bug fix", top_k=3)
        brief["recent_decisions"] = [
            {"text": lr.get("text", "")[:200], "type": lr.get("type", "")}
            for lr in recent
        ]
    except Exception:  # pylint: disable=broad-except
        pass

    # ── entry points from knowledge graph (top symbols by in-degree) ─────────
    try:
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        kg = KnowledgeGraph()
        if kg.G.number_of_nodes() > 0:
            top = sorted(
                [(n, d) for n, d in kg.G.in_degree() if not n.startswith("concept::")],
                key=lambda x: x[1],
                reverse=True,
            )[:5]
            brief["entry_points"] = [
                {"symbol": n.replace("symbol::", ""), "call_count": deg}
                for n, deg in top
            ]
    except Exception:  # pylint: disable=broad-except
        pass

    # ── hot symbols from behaviour tracker ───────────────────────────────────
    try:
        from graph.knowledge_graph import KnowledgeGraph as _KG  # pylint: disable=import-outside-toplevel
        from graph.behaviour_tracker import BehaviourTracker  # pylint: disable=import-outside-toplevel
        bt = BehaviourTracker(_KG())
        weights = bt.data.get("symbol_weights", {})
        hot = sorted(
            [(k, v.get("hit_count", 0)) for k, v in weights.items()],
            key=lambda x: x[1],
            reverse=True,
        )[:5]
        brief["hot_symbols"] = [
            {"symbol": k.split("::")[-1], "path": k, "score": round(v, 2)}
            for k, v in hot
        ]
    except Exception:  # pylint: disable=broad-except
        pass

    # ── index health ──────────────────────────────────────────────────────────
    try:
        with open(get_path("index/ast_index.json"), encoding="utf-8") as f:
            idx = json.load(f)
        brief["index_health"] = {
            "symbols": idx.get("total_symbols", 0),
            "files": len(idx.get("files", {})),
            "last_indexed": idx.get("indexed_at", "unknown"),
        }
    except (OSError, json.JSONDecodeError):
        brief["index_health"] = {"symbols": 0, "files": 0, "last_indexed": "not indexed"}

    # Cold-start guidance — tell agents what to run when data is missing
    if not brief["architecture"]:
        if brief["index_health"].get("symbols", 0) == 0:
            brief["setup_required"] = (
                "Index not built. Run: cognirepo index-repo . "
                "(then cognirepo summarize for architecture overview)"
            )
        else:
            brief["setup_required"] = (
                "Architecture summaries missing. Run: cognirepo summarize"
            )

    return brief
