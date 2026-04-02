# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tools/explain_change.py — answers "What changed in this file/function recently,
and what was the effect?"

Cross-references:
  - git log (via git_utils) for diff history
  - episodic memory for past events mentioning the same target
"""
from __future__ import annotations

import os

from tools.git_utils import git_log_patch, GitNotFoundError
from retrieval.hybrid import episodic_bm25_filter


def explain_change(
    target: str,
    since: str = "7d",
    max_commits: int = 10,
) -> dict:
    """
    Return a combined view of recent git changes + episodic memory for a target.

    Parameters
    ----------
    target      : File path (e.g. "auth.py") or function name
    since       : Time window — "7d", "30d", "1y", or ISO date "YYYY-MM-DD"
    max_commits : Max git commits to include

    Returns
    -------
    {
        "target": str,
        "since": str,
        "git_summary": {
            "commits": [...],
            "total_added": int,
            "total_removed": int,
        },
        "episodic_context": [...],
    }
    """
    repo_root = os.environ.get("COGNIREPO_ROOT", os.getcwd())

    # ── 1. git history ────────────────────────────────────────────────────────
    git_commits: list[dict] = []
    git_error: str | None = None
    try:
        git_commits = git_log_patch(
            target=target,
            since=since,
            max_commits=max_commits,
            repo_root=repo_root,
        )
    except GitNotFoundError as exc:
        git_error = str(exc)

    if git_error:
        return {"error": git_error}

    total_added = sum(c["diff_summary"]["added"] for c in git_commits)
    total_removed = sum(c["diff_summary"]["removed"] for c in git_commits)

    git_summary = {
        "commits": git_commits,
        "total_added": total_added,
        "total_removed": total_removed,
    }

    # ── 2. episodic context ───────────────────────────────────────────────────
    episodic: list[dict] = []
    try:
        episodic = episodic_bm25_filter(target, top_k=10)
    except Exception:  # pylint: disable=broad-except
        pass

    return {
        "target": target,
        "since": since,
        "git_summary": git_summary,
        "episodic_context": episodic,
    }


if __name__ == "__main__":
    import json
    import sys

    tgt = sys.argv[1] if len(sys.argv) > 1 else "retrieval/hybrid.py"
    since_arg = sys.argv[2] if len(sys.argv) > 2 else "30d"
    print(json.dumps(explain_change(tgt, since=since_arg), indent=2))
