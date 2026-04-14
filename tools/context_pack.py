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
  2. Confidence gate: if no code hit clears _MIN_CODE_CONFIDENCE, return
     structured failure — never return README noise for a code query.
  3. For each hit with a file:line source, extract a window of ±window_lines
  4. Optionally include episodic hits (episodic_bm25_filter)
  5. Pack sections greedily into max_tokens using tiktoken (cl100k_base)
  6. Return structured dict with query, token_count, sections[], truncated flag
  7. If autosave_context enabled, write to ~/.cognirepo/<repo>/last_context.json
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

from retrieval.hybrid import hybrid_retrieve, episodic_bm25_filter

try:
    import tiktoken as _tiktoken
    _ENC = _tiktoken.get_encoding("cl100k_base")
    _TIKTOKEN_OK = True
except ImportError:
    _ENC = None  # type: ignore[assignment]
    _TIKTOKEN_OK = False
except Exception:  # pylint: disable=broad-except
    _ENC = None  # type: ignore[assignment]
    _TIKTOKEN_OK = False


def _count_tokens(text: str) -> int:
    if not _TIKTOKEN_OK or _ENC is None:
        # Graceful fallback: ~4 chars per token (cl100k_base average)
        import logging as _logging  # pylint: disable=import-outside-toplevel
        _logging.getLogger(__name__).warning(
            "tiktoken not available — using char/4 token estimate. "
            "Run: pip install tiktoken"
        )
        return max(1, len(text) // 4)
    return len(_ENC.encode(text))

# ── confidence gate ────────────────────────────────────────────────────────────
# Minimum vector_score for a code hit to be considered confident.
# Below this threshold, context_pack returns a structured failure rather than
# README noise.  Set lower when the embedding model is weak or the repo is small.
_MIN_CODE_CONFIDENCE: float = float(os.environ.get("COGNIREPO_MIN_CONFIDENCE", "0.25"))

# Intent keywords: queries with these words get doc_index results in addition to code_index
_DOC_INTENT_PATTERN = re.compile(
    r"\b(how does|overview|architecture|what is|explain|describe|why does|design|"
    r"purpose|history|background|changelog|readme|documentation)\b",
    re.IGNORECASE,
)


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


def _is_doc_query(query: str) -> bool:
    """Return True when the query intent is architecture/overview/documentation."""
    return bool(_DOC_INTENT_PATTERN.search(query))


def _autosave_context(result: dict) -> None:
    """Write context_pack result to ~/.cognirepo/<repo>/last_context.json (best-effort)."""
    try:
        from config.paths import get_path  # pylint: disable=import-outside-toplevel
        import datetime  # pylint: disable=import-outside-toplevel
        config_path = get_path("config.json")
        if not os.path.exists(config_path):
            return
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
        if not cfg.get("autosave_context", True):
            return
        repo_name = cfg.get("project_name", os.path.basename(os.getcwd()))
        save_dir = os.path.join(os.path.expanduser("~"), ".cognirepo", repo_name)
        os.makedirs(save_dir, exist_ok=True)
        out = {
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "agent": "cognirepo",
            "repo": repo_name,
            **result,
        }
        with open(os.path.join(save_dir, "last_context.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
    except Exception:  # pylint: disable=broad-except
        pass  # autosave is always best-effort


def context_pack(
    query: str,
    max_tokens: int = 2000,
    include_episodic: bool = True,
    include_symbols: bool = True,
    window_lines: int = 15,
    file: str = "",
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
    file           : Optional file path — returns full file-scoped context

    Returns
    -------
    {
        "query": str,
        "token_count": int,
        "sections": [{"type", "source", "score", "content"}, ...],
        "truncated": bool
    }

    On no confident match:
    {
        "status": "no_confident_match",
        "best_score": float,
        "suggestion": str
    }
    """
    # ── file-mode: return all indexed context for a specific file ────────────
    if file:
        return _file_mode_context(file, max_tokens, window_lines)

    sections: list[dict] = []
    token_budget = max_tokens
    truncated = False

    # ── 1. hybrid retrieval (semantic + AST) — two-bucket architecture ──────
    if include_symbols:
        candidates = hybrid_retrieve(query, top_k=20)

        # Two-bucket split: code_index vs doc_index
        # code_hits: AST symbols (source == "ast") — always returned for code queries
        # other_hits: semantic memory, docs — returned only for doc-intent queries
        code_hits = [c for c in candidates if c.get("source") == "ast"]
        other_hits = [c for c in candidates if c.get("source") != "ast"]

        # ── confidence gate ────────────────────────────────────────────────
        # If no code hit clears the threshold, return structured failure.
        # This prevents README noise from being returned for code queries.
        best_score = max((c.get("vector_score", c.get("final_score", 0.0)) for c in code_hits), default=0.0)
        doc_intent = _is_doc_query(query)

        if code_hits and best_score < _MIN_CODE_CONFIDENCE and not doc_intent:
            # No confident code hit — check if any semantic hit is better
            best_semantic = max(
                (c.get("vector_score", c.get("final_score", 0.0)) for c in other_hits),
                default=0.0,
            )
            if best_semantic < _MIN_CODE_CONFIDENCE:
                result = {
                    "status": "no_confident_match",
                    "best_score": round(max(best_score, best_semantic), 4),
                    "suggestion": (
                        "run `cognirepo index-repo .` or use a more specific symbol name. "
                        "If the repo is freshly initialised, try `cognirepo seed --from-git` first."
                    ),
                }
                _autosave_context(result)
                return result

        # For doc-intent queries, allow other_hits up to 40% budget
        # For code queries, cap other_hits at 20%
        doc_cap = int(max_tokens * (0.40 if doc_intent else 0.20))
        doc_spent = 0

        def _process_candidate(cand: dict, is_code: bool) -> bool:
            """Append one candidate to sections. Returns False when budget is spent."""
            nonlocal token_budget, doc_spent, truncated

            text = cand.get("text", "")
            score = cand.get("final_score", 0.0)
            source_label = cand.get("source", "semantic")

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
                if window_text:
                    lines = window_text.splitlines()
                    while lines and _count_tokens("\n".join(lines)) > token_budget:
                        lines.pop()
                    content = "\n".join(lines)
                    tok = _count_tokens(content)

            if tok > token_budget:
                truncated = True
                return False

            if not is_code:
                if doc_spent + tok > doc_cap:
                    return True  # skip this doc hit but keep iterating
                doc_spent += tok

            # Label code vs doc hits for agent routing
            hit_type = "symbol" if source_label == "ast" else "doc_hit"
            sections.append({
                "type": hit_type,
                "source": file_ref or "memory",
                "score": round(score, 4),
                "content": content,
                "bucket": "code" if source_label == "ast" else "doc",
            })
            token_budget -= tok
            return True

        for cand in code_hits:
            if not _process_candidate(cand, is_code=True):
                break
        for cand in other_hits:
            if token_budget <= 0:
                truncated = True
                break
            _process_candidate(cand, is_code=False)

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
                    "bucket": "episodic",
                })
                token_budget -= tok
        except Exception:  # pylint: disable=broad-except
            pass

    total_tokens = max_tokens - token_budget
    result = {
        "query": query,
        "token_count": total_tokens,
        "sections": sections,
        "truncated": truncated,
    }
    _autosave_context(result)
    return result


def _file_mode_context(file_path: str, max_tokens: int, window_lines: int) -> dict:
    """Return all indexed context for a specific file (Cursor-style file mode)."""
    from indexer.ast_indexer import ASTIndexer  # pylint: disable=import-outside-toplevel
    from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel

    sections = []
    token_budget = max_tokens

    try:
        indexer = ASTIndexer(KnowledgeGraph())
        indexer.load()
        # Normalize path
        rel_path = file_path
        if os.path.isabs(file_path):
            repo_root = os.environ.get("COGNIREPO_ROOT", os.getcwd())
            rel_path = os.path.relpath(file_path, repo_root)

        file_data = indexer.index_data.get("files", {}).get(rel_path, {})
        symbols = file_data.get("symbols", [])

        for sym in symbols:
            content = _read_window(rel_path, sym["start_line"], window_lines)
            if not content:
                continue
            tok = _count_tokens(content)
            if tok > token_budget:
                break
            sections.append({
                "type": "symbol",
                "source": f"{rel_path}:{sym['start_line']}",
                "score": 1.0,
                "content": content,
                "bucket": "code",
                "symbol_name": sym["name"],
                "symbol_type": sym["type"],
            })
            token_budget -= tok
    except Exception:  # pylint: disable=broad-except
        pass

    result = {
        "query": f"file:{file_path}",
        "token_count": max_tokens - token_budget,
        "sections": sections,
        "truncated": token_budget <= 0,
    }
    _autosave_context(result)
    return result


if __name__ == "__main__":
    import json
    import sys

    q = " ".join(sys.argv[1:]) or "authentication logic"
    result = context_pack(q)
    print(json.dumps(result, indent=2))
