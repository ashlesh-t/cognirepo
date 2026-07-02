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

from core.config.paths import get_path

def _ast_index_file() -> str:
    return get_path("index/ast_index.json")
_SKIP_DIRS = {".git", "venv", ".venv", "__pycache__", "node_modules", ".cognirepo"}
# Filename substrings to skip — prevents test harness / CogniRepo internals from
# polluting search results (e.g. MANUAL_TEST_SUITE.md matching every test prompt).
_SKIP_FILE_SUBSTRINGS = {
    "MANUAL_TEST_SUITE",
    "TEST_SUITE",
    "test_suite",
    "MANUAL_TEST",
    # PR / issue templates add zero informational value as doc search results
    "PULL_REQUEST_TEMPLATE",
    "ISSUE_TEMPLATE",
    "pull_request_template",
    "issue_template",
}
# Path fragments that identify boilerplate directories to skip
_SKIP_PATH_FRAGMENTS = {".github", ".gitlab", ".bitbucket"}
_CONTEXT_LINES = 2  # lines before and after the matching line

# Semantic doc hits below this score are treated as no-match filler and dropped.
_MIN_DOC_SCORE = 0.05


def _should_skip_file(path: str) -> bool:
    """Return True if the file should be excluded from doc search results."""
    basename = os.path.basename(path)
    if any(sub in basename for sub in _SKIP_FILE_SUBSTRINGS):
        return True
    # Skip boilerplate directories (.github, .gitlab, …)
    norm = path.replace("\\", "/")
    return any(frag in norm for frag in _SKIP_PATH_FRAGMENTS)


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

    Search strategy (three-pass):
    0. Semantic vector search against doc chunks stored by DocIngester (primary).
       Returns relevant doc content even when the exact query words don't appear.
    1. Reverse-index fast path: check ast_index.json for .md token matches.
    2. Full recursive walk with string matching (fallback).

    Each dict contains:
      ``path``    — relative file path (or "semantic" for vector results)
      ``line``    — 1-based line number (0 for semantic results)
      ``context`` — surrounding lines or chunk text
      ``score``   — relevance score (semantic results only)
    """
    results: list[dict] = []

    # ── pass 0: semantic vector search against doc chunks (DocIngester output) ─
    try:
        from data.memory.embeddings import encode_with_timeout  # pylint: disable=import-outside-toplevel
        from data.memory.semantic_memory import SemanticMemory  # pylint: disable=import-outside-toplevel
        _mem = SemanticMemory()
        _qvec = encode_with_timeout(query).astype("float32")
        # Use search_with_scores so we get actual relevance scores, not 0.0.
        _hits = _mem.db.search_with_scores(_qvec, top_k=10)
        _seen_contexts: set[str] = set()
        for _h in _hits:
            _src = _h.get("source", "")
            _text = _h.get("text", "")
            # Only include doc-level hits (source tag set by DocIngester)
            if _src not in ("init_doc", "doc") and not (_src and _src.endswith((".md", ".rst"))):
                continue
            if not _text or _should_skip_file(_src):
                continue
            # Content-based filter for legacy chunks stored before the path-source fix:
            # skip obvious PR/issue template boilerplate (lots of HTML comments with N/A).
            if _text.count("<!--") >= 2 or (_text.count("<!--") >= 1 and "N/A" in _text):
                continue
            # Deduplicate by normalized text — chunked docs can produce
            # identical hits (whitespace variants included)
            _norm = " ".join(_text.split())
            if _norm in _seen_contexts:
                continue
            _seen_contexts.add(_norm)
            # combined_score = l2_score*0.8 + behaviour*0.2; l2_score = 1-dist/2
            _score = _h.get("combined_score", max(0.0, 1.0 - _h.get("l2_distance", 2.0) / 2.0))
            # Zero-score hits are FAISS filler, not matches — returning them
            # (observed: duplicate score-0.0 placeholder chunks) misleads
            # agents into treating noise as documentation.
            if _score < _MIN_DOC_SCORE:
                continue
            results.append({
                "path": _src if _src else "semantic",
                "line": 0,
                "context": _text,
                "score": round(_score, 4),
            })
    except Exception:  # pylint: disable=broad-except
        pass

    # ── pass 1: reverse index fast path ───────────────────────────────────────
    candidate_paths: set[str] = set()
    if os.path.exists(_ast_index_file()):
        try:
            with open(_ast_index_file(), encoding="utf-8") as f:
                idx = json.load(f)
            rev = idx.get("reverse_index", {})
            for token in query.lower().split():
                for entry in rev.get(token, []):
                    file_path = entry[0] if isinstance(entry, list) else entry
                    if file_path.endswith(".md") and not _should_skip_file(file_path):
                        candidate_paths.add(file_path)
        except (json.JSONDecodeError, OSError, IndexError):
            pass

    # ── pass 2: full recursive walk — covers the whole repo tree ──────────────
    for root, dirnames, files in os.walk("."):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in files:
            if not fname.endswith(".md"):
                continue
            path = os.path.join(root, fname)
            if _should_skip_file(path):
                continue
            if path in candidate_paths:
                continue
            try:
                with open(path, encoding="utf-8", errors="ignore") as fh:
                    if query.lower() in fh.read().lower():
                        candidate_paths.add(path)
            except OSError:
                pass

    # ── extract snippets from every string-match candidate ────────────────────
    for path in sorted(candidate_paths):
        results.extend(_extract_snippets(path, query))

    # Sort: semantic results first (have score), then string matches by path+line
    results.sort(key=lambda r: (-r.get("score", 0.0), r["path"], r["line"]))
    return results
