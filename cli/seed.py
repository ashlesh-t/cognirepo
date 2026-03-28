# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Seed the CogniRepo behaviour tracker from git log.

Parses `git log --name-only` for the last 100 commits and pre-populates
per-symbol hit counts proportional to recency:
  - committed within last  7 days  → weight 1.0
  - committed within last 30 days  → weight 0.5
  - older (within last 100 commits) → weight 0.1

Fail-silent if not in a git repo or git is unavailable.
Idempotent — skips if behaviour tracker already has symbol data.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone


_WEIGHT_7D  = 1.0
_WEIGHT_30D = 0.5
_WEIGHT_OLD = 0.1


def seed_from_git_log(
    repo_root: str = ".",
    dry_run: bool = False,
    tracker=None,
    indexer=None,
) -> dict:
    """
    Seed behaviour weights from recent git history.

    Parameters
    ----------
    repo_root : directory to treat as the git repo root (default: cwd)
    dry_run   : if True, print what would be written but write nothing
    tracker   : optional pre-built BehaviourTracker; created from disk if None
    indexer   : optional pre-built ASTIndexer; loaded from disk if None

    Returns a dict with "seeded" (count written) or "skipped" (reason).
    """
    # ── 1. resolve tracker ────────────────────────────────────────────────────
    if tracker is None:
        from graph.knowledge_graph import KnowledgeGraph        # pylint: disable=import-outside-toplevel
        from graph.behaviour_tracker import BehaviourTracker    # pylint: disable=import-outside-toplevel
        tracker = BehaviourTracker(graph=KnowledgeGraph())

    # idempotent guard
    if tracker.data.get("symbol_weights"):
        return {"skipped": "already seeded"}

    # ── 2. parse git log ──────────────────────────────────────────────────────
    abs_root = os.path.abspath(repo_root)
    try:
        proc = subprocess.run(  # nosec B603
            ["git", "-C", abs_root, "log", "--name-only",
             "--pretty=format:%aI", "-n", "100"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"skipped": "git not available"}

    if proc.returncode != 0:
        return {"skipped": "not a git repo"}

    # ── 3. collect file → max_weight mapping ─────────────────────────────────
    now = datetime.now(tz=timezone.utc)
    file_weights: dict[str, float] = {}
    current_date: datetime | None = None

    for raw_line in proc.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            dt = datetime.fromisoformat(line)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            current_date = dt
        except ValueError:
            if current_date is None:
                continue
            days_ago = (now - current_date).days
            if days_ago <= 7:
                w = _WEIGHT_7D
            elif days_ago <= 30:
                w = _WEIGHT_30D
            else:
                w = _WEIGHT_OLD
            if line not in file_weights or file_weights[line] < w:
                file_weights[line] = w

    if not file_weights:
        return {"seeded": 0}

    # ── 4. resolve symbols from AST index ────────────────────────────────────
    if indexer is None:
        from graph.knowledge_graph import KnowledgeGraph    # pylint: disable=import-outside-toplevel
        from indexer.ast_indexer import ASTIndexer          # pylint: disable=import-outside-toplevel
        indexer = ASTIndexer(graph=tracker.graph if hasattr(tracker, "graph") else KnowledgeGraph())
        indexer.load()

    seeds: list[tuple[str, float]] = []

    for file_path, weight in file_weights.items():
        file_data = indexer.index_data.get("files", {}).get(file_path, {})
        symbols = file_data.get("symbols", [])

        if symbols:
            for sym in symbols:
                node_id = f"{file_path}::{sym['name']}"
                seeds.append((node_id, weight))
        else:
            # no AST data — seed the file path as a fallback key
            seeds.append((file_path, weight))

    if dry_run:
        for node_id, weight in seeds:
            print(f"  would seed  {node_id}: {weight}")
        return {"would_seed": len(seeds)}

    # ── 5. write weights ──────────────────────────────────────────────────────
    sw = tracker.data.setdefault("symbol_weights", {})
    now_iso = now.isoformat()
    for node_id, weight in seeds:
        if node_id not in sw:
            sw[node_id] = {"hit_count": 0.0, "last_hit": None, "relevance_feedback": 0.0}
        # take max weight across all commits that touched this symbol
        sw[node_id]["hit_count"] = max(sw[node_id]["hit_count"], weight)
        sw[node_id]["last_hit"] = now_iso

    tracker.save()
    return {"seeded": len(seeds)}
