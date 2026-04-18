# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tools/semantic_search_code.py — semantic vector search over code symbols only.

Unlike retrieve_memory() which mixes episodic memories and code symbols,
this tool searches only the AST FAISS index (source="symbol") so results
are always code symbols, never episodic chat log entries.
"""
from __future__ import annotations

import os
from pathlib import Path

from memory.embeddings import get_model
from indexer.ast_indexer import ASTIndexer
from graph.knowledge_graph import KnowledgeGraph

# language label → file extensions mapping (for the optional language filter)
_LANG_EXTENSIONS: dict[str, set[str]] = {
    "python":     {".py"},
    "javascript": {".js", ".jsx", ".mjs"},
    "typescript": {".ts", ".tsx"},
    "go":         {".go"},
    "rust":       {".rs"},
    "java":       {".java"},
    "cpp":        {".cpp", ".cc", ".cxx", ".h", ".hpp"},
    "c":          {".c", ".h"},
}


def _lang_extensions(language: str | None) -> set[str] | None:
    """Return the set of file extensions for the given language name, or None."""
    if language is None:
        return None
    return _LANG_EXTENSIONS.get(language.lower())


def semantic_search_code(
    query: str,
    top_k: int = 5,
    language: str | None = None,
) -> list[dict]:
    """
    Semantic vector search over indexed code symbols only.

    Parameters
    ----------
    query    : Natural-language description of what to find
    top_k    : Maximum number of results to return
    language : Optional language filter — "python", "typescript", "go", etc.

    Returns
    -------
    List of dicts: [{name, type, file, line, score, language, docstring}]
    """
    model = get_model()
    graph = KnowledgeGraph()
    indexer = ASTIndexer(graph=graph)
    indexer.load()

    if indexer.faiss_index is None or indexer.faiss_index.ntotal == 0:
        return []

    query_vec = model.encode(query).astype("float32")

    # Over-fetch to allow for language filtering
    fetch_k = top_k * 5 if language else top_k * 2
    fetch_k = min(fetch_k, indexer.faiss_index.ntotal)

    import numpy as np  # pylint: disable=import-outside-toplevel

    distances, ids = indexer.faiss_index.search(
        np.array([query_vec], dtype="float32"), fetch_k
    )

    ext_filter = _lang_extensions(language)
    results: list[dict] = []

    for dist, fid in zip(distances[0], ids[0]):
        if fid < 0 or fid >= len(indexer.faiss_meta):
            continue
        meta = indexer.faiss_meta[fid]

        # all entries in the AST FAISS are symbols — but check tag for safety
        if meta.get("source", "symbol") != "symbol":
            continue

        file_path = meta.get("file", "")
        if ext_filter is not None:
            ext = Path(file_path).suffix.lower()
            if ext not in ext_filter:
                continue

        score = max(0.0, 1.0 - float(dist) / 2.0)
        file_lang = meta.get("language") or Path(file_path).suffix.lstrip(".")

        results.append({
            "name": meta.get("name", ""),
            "type": meta.get("type", ""),
            "file": file_path,
            "line": meta.get("start_line", -1),
            "score": round(score, 4),
            "language": file_lang,
            "docstring": meta.get("docstring", ""),
        })

        if len(results) == top_k:
            break

    # sort by score descending (already approximately sorted by FAISS, but re-sort after filter)
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]


if __name__ == "__main__":
    import json
    import sys

    q = " ".join(sys.argv[1:]) or "authentication logic"
    lang = os.environ.get("LANG_FILTER")
    print(json.dumps(semantic_search_code(q, language=lang), indent=2))
