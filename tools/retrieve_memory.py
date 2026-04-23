# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Tool to retrieve memory using hybrid retrieval
(FAISS vector similarity + knowledge graph proximity + behaviour weights).

Architecture rule (CLAUDE.md): tools/ must NOT call FAISS directly.
All retrieval goes through retrieval/hybrid.py.
"""
import sys

from retrieval.hybrid import hybrid_retrieve, MAX_QUERY_LEN
from server.metrics import MEMORY_OPS_TOTAL


def _dedup(results: list) -> list:
    """
    Remove entries that share the same file:line fingerprint as an earlier
    result.  This prevents retrieve_memory from echoing the same symbol
    pointer that semantic_search_code already returned.
    """
    seen: set[str] = set()
    deduped = []
    for entry in results:
        text = entry.get("text", "")
        # Extract "path:lineno" reference when the text follows the AST format
        # "FUNCTION foo in src/bar.py:42 — …"
        ref = None
        if " in " in text:
            try:
                ref = text.split(" in ", 1)[1].split(" — ")[0].strip()
            except IndexError:
                pass
        key = ref if ref else text[:120]
        if key not in seen:
            seen.add(key)
            deduped.append(entry)
    return deduped


def retrieve_memory(
    query: str,
    top_k: int = 5,
    structured: bool = False,
    min_score: float | None = None,
) -> list | dict:
    """
    Search for memories using hybrid retrieval.


    When structured=True, returns a structured dict:
    {
        "code_hits": [{"symbol", "file", "line", "score"}, ...],
        "doc_hits": [{"source", "section", "score"}, ...],
        "confidence": "high" | "medium" | "low"
    }

    When structured=False (default), returns flat list for backward compatibility:
      text, importance, source, final_score,
      vector_score, graph_score, behaviour_score

    min_score: filter results below this threshold (default 0.35).
               Pass 0.0 to disable. Configurable via COGNIREPO_MIN_RETRIEVAL_SCORE.

    Degrades gracefully: if the graph/index are empty (cold start),
    returns pure vector results with graph_score=0, behaviour_score=0.
    """
    if len(query) > MAX_QUERY_LEN:
        raise ValueError(
            f"Query too long ({len(query):,} chars > {MAX_QUERY_LEN:,}). "
            "Truncate or set COGNIREPO_MAX_QUERY_LEN env var."
        )
    try:
        results = hybrid_retrieve(query, top_k, min_score=min_score)
        results = _dedup(results)
        MEMORY_OPS_TOTAL.labels(op="retrieve", result="ok").inc()

        if structured:
            return _structure_results(results)
        return results
    except Exception:
        MEMORY_OPS_TOTAL.labels(op="retrieve", result="error").inc()
        raise


def _structure_results(results: list) -> dict:
    """
    Split flat hybrid results into code_hits + doc_hits buckets.
    Agents use code_hits immediately; doc_hits only when code hits insufficient.
    """
    code_hits = []
    doc_hits = []

    for r in results:
        text = r.get("text", "")
        score = r.get("final_score", r.get("importance", 0.0))
        source = r.get("source", "")

        if source == "ast" or (source == "semantic" and " in " in text and ":" in text):
            # AST hit: extract symbol + file:line
            symbol = ""
            file_path = ""
            line = 0
            if " in " in text:
                try:
                    parts = text.split(" in ", 1)
                    sym_part = parts[0].strip().split()
                    symbol = sym_part[-1] if sym_part else text[:40]
                    loc = parts[1].split(" — ")[0].strip()
                    if ":" in loc:
                        file_path, line_s = loc.rsplit(":", 1)
                        line = int(line_s)
                    else:
                        file_path = loc
                except (ValueError, IndexError):
                    symbol = text[:40]
            code_hits.append({
                "symbol": symbol or text[:40],
                "file": file_path,
                "line": line,
                "score": round(float(score), 4),
                "text": text,
            })
        else:
            # Doc/memory hit
            section = ""
            if "—" in text:
                section = text.split("—", 1)[1].strip()[:100]
            doc_hits.append({
                "source": source or "memory",
                "section": section or text[:80],
                "score": round(float(score), 4),
                "text": text,
            })

    # Determine confidence
    best_code = max((h["score"] for h in code_hits), default=0.0)
    best_doc = max((h["score"] for h in doc_hits), default=0.0)
    best = max(best_code, best_doc)
    if best >= 0.60:
        confidence = "high"
    elif best >= 0.35:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "code_hits": code_hits,
        "doc_hits": doc_hits,
        "confidence": confidence,
    }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        _results = retrieve_memory(sys.argv[1])
        for _r in _results:
            _score = _r.get("final_score", _r.get("importance", "?"))
            print(f"[{_score}] {_r.get('text', '')}")
    else:
        print("Usage: python tools/retrieve_memory.py <query>")
