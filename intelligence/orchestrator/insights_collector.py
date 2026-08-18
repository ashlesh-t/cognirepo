# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
intelligence/orchestrator/insights_collector.py — COGNIREPO-301 insights data collector.

Pure read-only aggregation for EPIC-300's repo-insights report: merged timeline
(COGNIREPO-204), git history, behaviour hot symbols, and graph stats/integrity.
Every source is a real record — no invented content. An empty source yields
{"status": "no_data"} for its section rather than being omitted.

No FAISS/embedding calls: this collects and shapes data already computed by
other stores, it does not perform retrieval.
"""
from __future__ import annotations

import contextlib
import json
import os
from datetime import date

from data.memory import timeline
from interface.tools import git_utils


@contextlib.contextmanager
def _scoped_to_repo(repo_root: str):
    """Scope KnowledgeGraph/BehaviourTracker/get_path() storage lookups to
    repo_root for the duration of the block, without touching module-level
    singletons or the process-wide override (thread-safe ContextVar).

    Mirrors interface/server/mcp_server.py::_repo_ctx — reimplemented locally
    rather than imported, since intelligence/orchestrator must not depend on
    interface/server (CLAUDE.md layering).
    """
    from core.config.paths import _CTX_DIR, get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel

    abs_root = os.path.abspath(repo_root)
    token = _CTX_DIR.set(get_cognirepo_dir_for_repo(abs_root))
    try:
        yield abs_root
    finally:
        _CTX_DIR.reset(token)


def _decisions_and_errors(since: str) -> tuple[dict, dict]:
    entries = timeline.merge(since=since, include_archived=True, limit=1000)
    decisions = [e for e in entries if e["kind"] == "decision"]
    errors = [e for e in entries if e["kind"] == "error"]
    return (
        {"status": "ok", "items": decisions} if decisions else {"status": "no_data", "items": []},
        {"status": "ok", "items": errors} if errors else {"status": "no_data", "items": []},
    )


def _timeline_section(since: str) -> dict:
    entries = timeline.merge(since=since, include_archived=True, limit=200)
    if not entries:
        return {"status": "no_data", "entries": [], "rollup": timeline.rollup([])}
    return {"status": "ok", "entries": entries, "rollup": timeline.rollup(entries)}


def _branches_section(repo_root: str) -> dict:
    branches = git_utils.list_branches(repo_root=repo_root)
    if not branches:
        return {"status": "no_data", "items": []}
    return {"status": "ok", "items": branches}


def _commits_by_week(repo_root: str, since: str) -> dict:
    commits = git_utils.git_log_patch(target=".", since=since, max_commits=500, repo_root=repo_root)
    if not commits:
        return {"status": "no_data", "weeks": []}

    weeks: dict[str, dict] = {}
    for c in commits:
        # c["date"] is "YYYY-MM-DD HH:MM:SS +ZZZZ" (git --format=%ai) — ISO week
        # bucket only needs the date portion, no timezone conversion.
        date_part = c["date"].split(" ")[0]
        year, week, _ = date.fromisoformat(date_part).isocalendar()
        key = f"{year}-W{week:02d}"
        bucket = weeks.setdefault(key, {"week": key, "commits": 0, "added": 0, "removed": 0})
        bucket["commits"] += 1
        bucket["added"] += c["diff_summary"]["added"]
        bucket["removed"] += c["diff_summary"]["removed"]

    return {"status": "ok", "weeks": [weeks[k] for k in sorted(weeks)]}


def _hot_symbols_section() -> dict:
    from data.graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
    from data.graph.behaviour_tracker import BehaviourTracker  # pylint: disable=import-outside-toplevel

    hot = BehaviourTracker(KnowledgeGraph()).get_hot_symbols(top_k=10)
    if not hot:
        return {"status": "no_data", "items": []}
    return {"status": "ok", "items": hot}


def _index_health_section(repo_root: str) -> dict:
    from core.config.paths import get_path  # pylint: disable=import-outside-toplevel

    try:
        with open(get_path("index/ast_index.json"), encoding="utf-8") as f:
            idx = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"status": "no_data", "symbols": 0, "files": 0, "last_indexed": "not indexed"}

    from data.graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel

    graph = KnowledgeGraph()
    return {
        "status": "ok",
        "symbols": idx.get("total_symbols", 0),
        "files": len(idx.get("files", {})),
        "last_indexed": idx.get("indexed_at", "unknown"),
        "graph_stats": graph.stats(),
        "integrity": graph.integrity_report(repo_root),
    }


def collect(repo_root: str, since: str = "90d") -> dict:
    """Aggregate real, already-stored records for the repo-insights report.

    Sections: meta, timeline, decisions, errors, branches, commits_by_week,
    hot_symbols, index_health. No section ever invents content — an empty
    source yields {"status": "no_data", ...}; git-derived sections (branches,
    commits_by_week) are populated regardless of .cognirepo state since they
    read the repo's own history, not CogniRepo storage.
    """
    abs_root = os.path.abspath(repo_root)
    branches = _branches_section(abs_root)
    commits_by_week = _commits_by_week(abs_root, since)

    with _scoped_to_repo(abs_root):
        timeline_section = _timeline_section(since)
        decisions, errors = _decisions_and_errors(since)
        hot_symbols = _hot_symbols_section()
        index_health = _index_health_section(abs_root)

    return {
        "meta": {"repo_root": abs_root, "since": since},
        "timeline": timeline_section,
        "decisions": decisions,
        "errors": errors,
        "branches": branches,
        "commits_by_week": commits_by_week,
        "hot_symbols": hot_symbols,
        "index_health": index_health,
    }
