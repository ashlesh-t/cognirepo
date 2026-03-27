# SPDX-FileCopyrightText: 2026 Ashlesh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/your-username/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Graph and AST routes — thin HTTP wrappers around KnowledgeGraph and ASTIndexer.

GET /graph/symbol/{name}           — lookup all locations for a symbol
GET /graph/callers/{function_name} — find every caller of a function
GET /graph/subgraph/{entity}       — local neighbourhood of a concept / symbol
GET /graph/stats                   — node count, edge count, top concepts
"""
import json
import os

from fastapi import APIRouter, Query

from graph.knowledge_graph import EdgeType

router = APIRouter(prefix="/graph", tags=["graph"])

# ── lazy singletons ───────────────────────────────────────────────────────────

_graph = None
_indexer = None


def _get_graph():
    global _graph
    if _graph is None:
        from graph.knowledge_graph import KnowledgeGraph
        _graph = KnowledgeGraph()
    return _graph


def _get_indexer():
    global _indexer
    if _indexer is None:
        from indexer.ast_indexer import ASTIndexer
        _indexer = ASTIndexer(_get_graph())
        _indexer.load()
    return _indexer


_EMPTY_GRAPH_WARNING = {
    "warning": "Graph is empty. Run 'cognirepo index-repo .' first.",
    "results": [],
}


def _graph_is_empty() -> bool:
    return _get_graph().G.number_of_nodes() == 0


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("/symbol/{name}")
def symbol_lookup(name: str):
    """Return all locations where *name* is defined, with file, line, and type."""
    if _graph_is_empty():
        return _EMPTY_GRAPH_WARNING
    indexer = _get_indexer()
    locations = indexer.lookup_symbol(name)
    result = []
    for loc in locations:
        file_path = loc["file"]
        line = loc["line"]
        sym_type = "UNKNOWN"
        file_data = indexer.index_data["files"].get(file_path, {})
        for sym in file_data.get("symbols", []):
            if sym["name"] == name and sym["start_line"] == line:
                sym_type = sym["type"]
                break
        result.append({"file": file_path, "line": line, "type": sym_type})
    return result


@router.get("/callers/{function_name}")
def callers(function_name: str):
    """Return every caller of *function_name* across the indexed repo."""
    if _graph_is_empty():
        return _EMPTY_GRAPH_WARNING
    graph = _get_graph()
    callee_node = f"symbol::{function_name}"
    if not graph.node_exists(callee_node):
        return []
    result = []
    for caller in graph.G.predecessors(callee_node):
        edge_data = graph.G[caller][callee_node]
        if edge_data.get("rel") == EdgeType.CALLED_BY:
            node_data = dict(graph.G.nodes[caller])
            result.append({
                "caller": caller,
                "file": node_data.get("file", ""),
                "line": node_data.get("line", -1),
            })
    return result


@router.get("/subgraph/{entity}")
def subgraph(entity: str, depth: int = Query(default=2, ge=1, le=5)):
    """Return the ego-graph around *entity* as {nodes, edges}."""
    if _graph_is_empty():
        return _EMPTY_GRAPH_WARNING
    graph = _get_graph()
    candidates = [entity, f"symbol::{entity}", f"concept::{entity.lower()}"]
    for candidate in candidates:
        if graph.node_exists(candidate):
            return graph.subgraph_around(candidate, radius=depth)
    return {"nodes": [], "edges": []}


@router.get("/stats")
def stats():
    """Return a health summary of the current graph state."""
    graph = _get_graph()
    s = graph.stats()
    concept_nodes = [
        n for n, d in graph.G.nodes(data=True) if d.get("type") == "CONCEPT"
    ]
    top_concepts = sorted(
        concept_nodes,
        key=lambda n: graph.G.degree(n),
        reverse=True,
    )[:5]
    last_indexed = None
    ast_index_path = ".cognirepo/index/ast_index.json"
    if os.path.exists(ast_index_path):
        with open(ast_index_path, encoding="utf-8") as f:
            last_indexed = json.load(f).get("indexed_at")
    return {
        "node_count": s["nodes"],
        "edge_count": s["edges"],
        "top_concepts": top_concepts,
        "last_indexed": last_indexed,
    }
