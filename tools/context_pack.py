# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tools/context_pack.py — budget-pack retrieved code/episodic context into a
token-bounded block that Claude can inject directly into its next prompt.

Steps:
  1. hybrid_retrieve(query, top_k=20) → ranked candidates
  2. For each hit with a file:line source, extract a window of ±window_lines
  3. Optionally include episodic hits (episodic_bm25_filter)
  4. Pack sections greedily into max_tokens using tiktoken (cl100k_base)
  5. Return structured dict with query, token_count, sections[], truncated flag
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from retrieval.hybrid import hybrid_retrieve, episodic_bm25_filter

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")

    def _count_tokens(text: str) -> int:
        return len(_ENC.encode(text))
except Exception:  # pylint: disable=broad-except
    # fallback: rough estimate (1 token ≈ 4 chars)
    def _count_tokens(text: str) -> int:  # type: ignore[misc]
        return max(1, len(text) // 4)


def _read_window(file_path: str, center_line: int, window_lines: int) -> str:
    """
    Read ±window_lines around center_line from file_path.
    Returns the extracted text, or empty string if the file is unreadable.
    """
    repo_root = os.environ.get("COGNIREPO_ROOT", os.getcwd())
    abs_path = (
        file_path if os.path.isabs(file_path)
        else os.path.join(repo_root, file_path)
    )
    try:
        lines = Path(abs_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    start = max(0, center_line - window_lines - 1)
    end = min(len(lines), center_line + window_lines)
    return "\n".join(lines[start:end])


def context_pack(
    query: str,
    max_tokens: int = 2000,
    include_episodic: bool = True,
    include_symbols: bool = True,
    window_lines: int = 15,
) -> dict:
    """
    Pack the most relevant code/episodic context into a token-bounded block.

    Parameters
    ----------
    query          : Natural-language question or intent
    max_tokens     : Hard budget for the combined output (default 2000)
    include_episodic: Whether to include episodic memory hits
    include_symbols : Whether to include AST/symbol hits with file windows
    window_lines   : Lines of code context above/below each hit

    Returns
    -------
    {
        "query": str,
        "token_count": int,
        "sections": [{"type", "source", "score", "content"}, ...],
        "truncated": bool
    }
    """
    sections: list[dict] = []
    token_budget = max_tokens
    truncated = False

    # ── 1. hybrid retrieval (semantic + AST) ────────────────────────────────
    if include_symbols:
        candidates = hybrid_retrieve(query, top_k=20)
        for cand in candidates:
            text = cand.get("text", "")
            score = cand.get("final_score", 0.0)
            source_label = cand.get("source", "semantic")

            # try to extract a file:line reference and pull a code window
            file_ref: Optional[str] = None
            window_text: Optional[str] = None

            if source_label == "ast" and " in " in text:
                # format: "FUNCTION foo in src/bar.py:42 — docstring"
                try:
                    location_part = text.split(" in ", 1)[1].split(" — ")[0]
                    if ":" in location_part:
                        fpath, lineno_str = location_part.rsplit(":", 1)
                        lineno = int(lineno_str)
                        window_text = _read_window(fpath, lineno, window_lines)
                        file_ref = f"{fpath}:{lineno}"
                except (ValueError, IndexError):
                    pass

            content = window_text if window_text else text
            tok = _count_tokens(content)

            if tok > token_budget:
                # try to trim the window if it's a code block
                if window_text:
                    lines = window_text.splitlines()
                    while lines and _count_tokens("\n".join(lines)) > token_budget:
                        lines.pop()
                    content = "\n".join(lines)
                    tok = _count_tokens(content)

            if tok > token_budget:
                truncated = True
                break

            sections.append({
                "type": "symbol" if source_label == "ast" else "doc",
                "source": file_ref or "memory",
                "score": round(score, 4),
                "content": content,
            })
            token_budget -= tok

    # ── 2. episodic hits ─────────────────────────────────────────────────────
    if include_episodic and token_budget > 0:
        try:
            ep_hits = episodic_bm25_filter(query, top_k=5)
            for ep in ep_hits:
                event_text = ep.get("event", "")
                metadata = ep.get("metadata", {})
                meta_str = "; ".join(f"{k}={v}" for k, v in metadata.items())
                content = f"{event_text}" + (f" [{meta_str}]" if meta_str else "")
                tok = _count_tokens(content)
                if tok > token_budget:
                    truncated = True
                    break
                sections.append({
                    "type": "episodic",
                    "source": ep.get("time", ""),
                    "score": 0.0,
                    "content": content,
                })
                token_budget -= tok
        except Exception:  # pylint: disable=broad-except
            pass

    total_tokens = max_tokens - token_budget
    return {
        "query": query,
        "token_count": total_tokens,
        "sections": sections,
        "truncated": truncated,
    }


if __name__ == "__main__":
    import json
    import sys

    q = " ".join(sys.argv[1:]) or "authentication logic"
    result = context_pack(q)
    print(json.dumps(result, indent=2))
