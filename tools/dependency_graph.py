# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tools/dependency_graph.py — expose import/dependency relationships in a
Claude-friendly format.

Strategy:
  1. Walk the AST index to find all symbols defined in `module`.
  2. For each symbol, look up its `calls` list (from ast_index.json).
  3. Cross-reference each callee against the reverse_index to find which
     files define that callee → those files are "imports" of `module`.
  4. For "imported_by": find all other files whose symbols call anything
     defined in `module`.
  5. Repeat transitively up to `depth` hops.
"""
from __future__ import annotations

import os
from collections import deque
from pathlib import Path

from graph.knowledge_graph import KnowledgeGraph
from indexer.ast_indexer import ASTIndexer


def _load_indexer() -> ASTIndexer:
    graph = KnowledgeGraph()
    indexer = ASTIndexer(graph=graph)
    indexer.load()
    return indexer


def _direct_imports(module: str, indexer: ASTIndexer) -> list[str]:
    """Files that `module` imports (its symbols call symbols defined in them)."""
    file_data = indexer.index_data.get("files", {}).get(module, {})
    if not file_data:
        return []

    rev = indexer.index_data.get("reverse_index", {})
    imports: set[str] = set()

    for sym in file_data.get("symbols", []):
        for callee in sym.get("calls", []):
            for loc in rev.get(callee, []):
                other_file = loc[0]
                if other_file != module:
                    imports.add(other_file)

    return sorted(imports)


def _direct_imported_by(module: str, indexer: ASTIndexer) -> list[str]:
    """Files that import `module` (their symbols call symbols defined in module)."""
    file_data = indexer.index_data.get("files", {}).get(module, {})
    if not file_data:
        return []

    # symbols defined in `module`
    local_symbols: set[str] = {s["name"] for s in file_data.get("symbols", [])}
    if not local_symbols:
        return []

    imported_by: set[str] = set()
    for other_file, other_data in indexer.index_data.get("files", {}).items():
        if other_file == module:
            continue
        for sym in other_data.get("symbols", []):
            if any(c in local_symbols for c in sym.get("calls", [])):
                imported_by.add(other_file)
                break

    return sorted(imported_by)


def _transitive(
    module: str,
    indexer: ASTIndexer,
    direction: str,
    max_depth: int,
) -> list[str]:
    """BFS to collect all transitive dependencies up to max_depth hops."""
    if max_depth <= 1:
        return []

    visited: set[str] = {module}
    queue: deque[tuple[str, int]] = deque()

    direct_fn = _direct_imports if direction == "imports" else _direct_imported_by
    for f in direct_fn(module, indexer):
        if f not in visited:
            visited.add(f)
            queue.append((f, 1))

    result: list[str] = []
    while queue:
        current, depth = queue.popleft()
        result.append(current)
        if depth < max_depth - 1:
            for f in direct_fn(current, indexer):
                if f not in visited:
                    visited.add(f)
                    queue.append((f, depth + 1))

    return result


def dependency_graph(
    module: str,
    direction: str = "both",
    depth: int = 2,
) -> dict:
    """
    Return the dependency relationships for a module.

    Parameters
    ----------
    module    : Relative file path (e.g. "retrieval/hybrid.py")
    direction : "imports" | "imported_by" | "both"
    depth     : Transitive traversal depth (1 = direct only)

    Returns
    -------
    {
        "module": str,
        "imports": [...],
        "imported_by": [...],
        "transitive_imports": [...],
        "depth": int
    }
    """
    if direction not in ("imports", "imported_by", "both"):
        return {"error": f"direction must be 'imports', 'imported_by', or 'both', got: {direction!r}"}

    indexer = _load_indexer()
    files = indexer.index_data.get("files", {})

    if module not in files:
        # try partial match (filename without path)
        matches = [f for f in files if Path(f).name == module or f.endswith("/" + module)]
        if len(matches) == 1:
            module = matches[0]
        elif not matches:
            return {"error": f"module not found in graph: {module!r}"}
        else:
            return {"error": f"ambiguous module name {module!r}; matches: {matches}"}

    result: dict = {"module": module, "depth": depth}

    if direction in ("imports", "both"):
        result["imports"] = _direct_imports(module, indexer)
        result["transitive_imports"] = _transitive(module, indexer, "imports", depth)
    else:
        result["imports"] = []
        result["transitive_imports"] = []

    if direction in ("imported_by", "both"):
        result["imported_by"] = _direct_imported_by(module, indexer)
    else:
        result["imported_by"] = []

    return result


if __name__ == "__main__":
    import json
    import sys

    mod = sys.argv[1] if len(sys.argv) > 1 else "retrieval/hybrid.py"
    print(json.dumps(dependency_graph(mod), indent=2))
