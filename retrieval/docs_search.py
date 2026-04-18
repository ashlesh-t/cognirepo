# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Module for searching through markdown files in the repository.

Returns content snippets (not just file paths) so callers can display
matching text alongside the file location — similar to ``grep -C 2``.

Search strategy (two-pass):
  1. Reverse-index fast path: extract tokens from query, look up in
     ast_index.json reverse_index for matching .md entries — O(1) per token.
  2. Full-text recursive walk: os.walk starting at "." catches all .md files
     including those deep inside the repo tree.

Results are deduplicated (same file:line pair only appears once).
Each result dict has keys: ``path``, ``line`` (1-based), ``context`` (str).
"""
from __future__ import annotations

import json
import os

from config.paths import get_path

def _ast_index_file() -> str:
    return get_path("index/ast_index.json")
_SKIP_DIRS = {".git", "venv", ".venv", "__pycache__", "node_modules", ".cognirepo"}
_CONTEXT_LINES = 2  # lines before and after the matching line


# ── snippet extractor ─────────────────────────────────────────────────────────

def _extract_snippets(path: str, query: str) -> list[dict]:
    """
    Open *path*, find every line matching *query* (case-insensitive),
    and return a list of dicts with ``path``, ``line``, ``context``.

    *context* is a multi-line string containing *CONTEXT_LINES* lines before
    and after the matching line, joined by newlines.
    """
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()
    except OSError:
        return []

    q_lower = query.lower()
    results: list[dict] = []
    seen_lines: set[int] = set()

    for i, line in enumerate(lines):
        if q_lower not in line.lower():
            continue
        if i in seen_lines:
            continue
        seen_lines.add(i)

        start = max(0, i - _CONTEXT_LINES)
        end = min(len(lines), i + _CONTEXT_LINES + 1)
        context_block = "".join(lines[start:end]).rstrip()

        results.append({
            "path":    path,
            "line":    i + 1,       # 1-based
            "context": context_block,
        })

    return results


# ── public search function ────────────────────────────────────────────────────

def search_docs(query: str) -> list[dict]:
    """
    Search for *query* in all ``.md`` files under the current directory tree
    (recursively) and return a list of match dicts.

    Each dict contains:
      ``path``    — relative file path
      ``line``    — 1-based line number of the first matching line in this snippet
      ``context`` — surrounding lines (±2) as a single string

    Results are sorted by path then line number.
    """
    candidate_paths: set[str] = set()

    # ── fast path: reverse index gives candidate .md files ────────────────────
    if os.path.exists(_ast_index_file()):
        try:
            with open(_ast_index_file(), encoding="utf-8") as f:
                idx = json.load(f)
            rev = idx.get("reverse_index", {})
            for token in query.lower().split():
                for entry in rev.get(token, []):
                    file_path = entry[0] if isinstance(entry, list) else entry
                    if file_path.endswith(".md"):
                        candidate_paths.add(file_path)
        except (json.JSONDecodeError, OSError, IndexError):
            pass  # fall through to full-text scan

    # ── full recursive walk — covers the whole repo tree ─────────────────────
    for root, dirnames, files in os.walk("."):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in files:
            if not fname.endswith(".md"):
                continue
            path = os.path.join(root, fname)
            if path in candidate_paths:
                continue  # already a candidate; will be scanned below
            # Quick content check before full snippet extraction
            try:
                with open(path, encoding="utf-8", errors="ignore") as fh:
                    if query.lower() in fh.read().lower():
                        candidate_paths.add(path)
            except OSError:
                pass

    # ── extract snippets from every candidate ─────────────────────────────────
    results: list[dict] = []
    for path in sorted(candidate_paths):
        results.extend(_extract_snippets(path, query))

    # Sort: path ascending, then line number ascending
    results.sort(key=lambda r: (r["path"], r["line"]))
    return results
