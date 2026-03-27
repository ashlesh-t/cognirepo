# SPDX-FileCopyrightText: 2026 Ashlesh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/your-username/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Real MCP server for CogniRepo — stdio transport, works with Claude Desktop
and any stdio MCP client.
"""
import json
import os
from mcp.server.fastmcp import FastMCP

from tools.store_memory import store_memory as _store_memory
from tools.retrieve_memory import retrieve_memory as _retrieve_memory
from retrieval.docs_search import search_docs as _search_docs
from memory.episodic_memory import log_event, get_history

mcp = FastMCP("cognirepo")

# ── lazy singletons for graph + indexer ──────────────────────────────────────
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


@mcp.tool()
def store_memory(text: str, source: str = "") -> dict:
    """Store a semantic memory with an optional source label."""
    return _store_memory(text, source)


@mcp.tool()
def retrieve_memory(query: str, top_k: int = 5) -> list:
    """Retrieve the top-k memories most similar to the query."""
    return _retrieve_memory(query, top_k)


@mcp.tool()
def search_docs(query: str) -> list:
    """Search all markdown documentation files for the given query string."""
    return _search_docs(query)


@mcp.tool()
def log_episode(event: str, metadata: dict = None) -> dict:
    """Append an episodic event with optional metadata to the event log."""
    log_event(event, metadata or {})
    return {"status": "logged", "event": event}


@mcp.tool()
def lookup_symbol(name: str) -> dict:
    """Return all locations where a symbol is defined or called, with file, line, and type."""
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


@mcp.tool()
def who_calls(function_name: str) -> dict:
    """Return every caller of a function across the indexed repo."""
    if _graph_is_empty():
        return _EMPTY_GRAPH_WARNING
    from graph.knowledge_graph import EdgeType
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


@mcp.tool()
def subgraph(entity: str, depth: int = 2) -> dict:
    """Return the local neighbourhood of a concept or symbol as {nodes, edges}."""
    if _graph_is_empty():
        return _EMPTY_GRAPH_WARNING
    graph = _get_graph()
    candidates = [entity, f"symbol::{entity}", f"concept::{entity.lower()}"]
    for candidate in candidates:
        if graph.node_exists(candidate):
            return graph.subgraph_around(candidate, radius=depth)
    return {"nodes": [], "edges": []}


@mcp.tool()
def episodic_search(query: str, limit: int = 10) -> list:
    """Return past episodic events matching a keyword query."""
    query_lower = query.lower()
    events = get_history(limit=10000)
    matches = []
    for event in events:
        if query_lower in json.dumps(event).lower():
            matches.append(event)
            if len(matches) >= limit:
                break
    return matches


@mcp.tool()
def graph_stats() -> dict:
    """Return a health summary of the current graph state."""
    graph = _get_graph()
    stats = graph.stats()
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
        "node_count": stats["nodes"],
        "edge_count": stats["edges"],
        "top_concepts": top_concepts,
        "last_indexed": last_indexed,
    }


def _build_manifest() -> dict:
    """Return the tool-schema manifest so non-MCP clients can read it."""
    return {
        "name": "cognirepo",
        "version": "0.1.0",
        "transport": "stdio",
        "tools": [
            {
                "name": "store_memory",
                "description": "Store a semantic memory with an optional source label.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text":   {"type": "string", "description": "Memory text to store"},
                        "source": {"type": "string", "description": "Origin label (file, url, …)", "default": ""},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "retrieve_memory",
                "description": "Retrieve the top-k memories most similar to the query.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "top_k": {"type": "integer", "description": "Number of results", "default": 5},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "search_docs",
                "description": "Search all markdown documentation files for the given query string.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Text to search for in .md files"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "log_episode",
                "description": "Append an episodic event with optional metadata to the event log.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "event":    {"type": "string", "description": "Event description"},
                        "metadata": {"type": "object", "description": "Arbitrary key-value metadata", "default": {}},
                    },
                    "required": ["event"],
                },
            },
            {
                "name": "lookup_symbol",
                "description": "Return all locations where a symbol is defined or called, with file, line, and type.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Symbol name to look up"},
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "who_calls",
                "description": "Return every caller of a function across the indexed repo.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "function_name": {"type": "string", "description": "Name of the function to look up callers for"},
                    },
                    "required": ["function_name"],
                },
            },
            {
                "name": "subgraph",
                "description": "Return the local neighbourhood of a concept or symbol as {nodes, edges}.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity": {"type": "string", "description": "Entity name or node ID to centre the subgraph on"},
                        "depth":  {"type": "integer", "description": "BFS radius", "default": 2},
                    },
                    "required": ["entity"],
                },
            },
            {
                "name": "episodic_search",
                "description": "Return past episodic events matching a keyword query.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Keyword to search for in event log"},
                        "limit": {"type": "integer", "description": "Maximum number of results", "default": 10},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "graph_stats",
                "description": "Return a health summary of the current graph state.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        ],
    }


def _write_manifest() -> None:
    manifest_path = os.path.join(os.path.dirname(__file__), "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(_build_manifest(), f, indent=2)


def run_server() -> None:
    """Entry point called by the CLI — writes manifest then starts stdio MCP server."""
    _write_manifest()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
