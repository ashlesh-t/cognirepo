# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tools/git_utils.py — reusable git subprocess helpers for CogniRepo tools.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path


class GitNotFoundError(RuntimeError):
    """Raised when the target path is not inside a git repository."""


def _find_git_root(start_path: str) -> str:
    """Walk up from start_path to find the .git directory."""
    p = Path(start_path).resolve()
    for candidate in [p, *p.parents]:
        if (candidate / ".git").exists():
            return str(candidate)
    raise GitNotFoundError(f"not a git repository (or any parent): {start_path}")


def git_log_patch(
    target: str,
    since: str = "7d",
    max_commits: int = 10,
    repo_root: str | None = None,
) -> list[dict]:
    """
    Run `git log --patch --follow -- <target>` and parse the output.

    Parameters
    ----------
    target      : File path or function name to query
    since       : "7d", "30d", "1y", or ISO date string (YYYY-MM-DD)
    max_commits : Maximum number of commits to return
    repo_root   : Git repo root (auto-detected from CWD if None)

    Returns
    -------
    List of commit dicts:
    [{hash, author, date, message, diff_summary: {added, removed, hunks}}]
    """
    if repo_root is None:
        import os  # pylint: disable=import-outside-toplevel
        repo_root = _find_git_root(os.getcwd())

    since_flag = _parse_since(since)

    cmd = [
        "git", "log",
        "--patch",
        "--follow",
        f"--max-count={max_commits}",
        f"--since={since_flag}",
        "--format=COMMIT_SEP%n%H%n%an%n%ai%n%s",
        "--",
        target,
    ]

    try:
        proc = subprocess.run(
            cmd,
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise GitNotFoundError("git executable not found") from exc

    if proc.returncode != 0:
        return []

    return _parse_git_log_output(proc.stdout)


def _parse_since(since: str) -> str:
    """Convert '7d', '30d', '1y' or ISO date to a git --since= value."""
    # already ISO date
    if re.match(r"^\d{4}-\d{2}-\d{2}", since):
        return since
    m = re.match(r"^(\d+)([dDwWmMyY])$", since)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        days = {"d": n, "w": n * 7, "m": n * 30, "y": n * 365}.get(unit, n)
        dt = datetime.now(tz=timezone.utc) - timedelta(days=days)
        return dt.strftime("%Y-%m-%d")
    # fallback — pass through as-is
    return since


def _parse_git_log_output(raw: str) -> list[dict]:
    """Parse the COMMIT_SEP-delimited git log --patch output."""
    commits: list[dict] = []
    blocks = raw.split("COMMIT_SEP\n")
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        if len(lines) < 4:
            continue
        commit_hash = lines[0].strip()
        author = lines[1].strip()
        date = lines[2].strip()
        message = lines[3].strip()
        diff_lines = lines[4:]

        added = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))
        hunks = sum(1 for l in diff_lines if l.startswith("@@"))

        commits.append({
            "hash": commit_hash,
            "author": author,
            "date": date,
            "message": message,
            "diff_summary": {
                "added": added,
                "removed": removed,
                "hunks": hunks,
            },
        })
    return commits
