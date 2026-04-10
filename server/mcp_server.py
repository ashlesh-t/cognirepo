# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Real MCP server for CogniRepo — stdio transport, works with Claude Desktop
and any stdio MCP client.
"""
# pylint: disable=duplicate-code
import json
import logging
import os
from mcp.server.fastmcp import FastMCP

from config.logging import setup_logging, new_trace_id

setup_logging()
logger = logging.getLogger(__name__)

from tools.store_memory import store_memory as _store_memory
from tools.retrieve_memory import retrieve_memory as _retrieve_memory
from tools.context_pack import context_pack as _context_pack
from tools.semantic_search_code import semantic_search_code as _semantic_search_code
from tools.dependency_graph import dependency_graph as _dependency_graph
from tools.explain_change import explain_change as _explain_change
from retrieval.docs_search import search_docs as _search_docs
from memory.episodic_memory import log_event, get_history, search_episodes
from memory.learning_store import get_learning_store, auto_tag
from server.learning_middleware import intercept_after_store, intercept_after_episode

mcp = FastMCP("cognirepo")

# ── lazy singletons for graph + indexer ──────────────────────────────────────
_GRAPH = None  # pylint: disable=invalid-name
_INDEXER = None  # pylint: disable=invalid-name


def _get_graph():
    """Lazily load KnowledgeGraph."""
    global _GRAPH  # pylint: disable=global-statement
    if _GRAPH is None:
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        _GRAPH = KnowledgeGraph()
    return _GRAPH


def _get_indexer():
    """Lazily load ASTIndexer."""
    global _INDEXER  # pylint: disable=global-statement
    if _INDEXER is None:
        from indexer.ast_indexer import ASTIndexer  # pylint: disable=import-outside-toplevel
        _INDEXER = ASTIndexer(_get_graph())
        _INDEXER.load()
    return _INDEXER


_EMPTY_GRAPH_WARNING = {
    "warning": "Graph is empty. Run 'cognirepo index-repo .' first.",
    "results": [],
}


def _graph_is_empty() -> bool:
    return _get_graph().G.number_of_nodes() == 0


def _traced(tool_name: str, fn, *args, **kwargs):
    """Run a tool function with a fresh trace ID per call."""
    tid = new_trace_id()
    logger.info("mcp.tool.start", extra={"tool": tool_name, "trace_id": tid})
    try:
        result = fn(*args, **kwargs)
        logger.info("mcp.tool.end", extra={"tool": tool_name, "status": "ok"})
        return result
    except Exception:
        logger.exception("mcp.tool.error", extra={"tool": tool_name})
        raise


@mcp.tool()
def store_memory(text: str, source: str = "") -> dict:
    """Store a semantic memory with an optional source label."""
    result = _traced("store_memory", _store_memory, text, source)
    # Auto-learning middleware: capture corrections/decisions/prod-issues
    intercept_after_store(text, source=source)
    return result


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
    intercept_after_episode(event, metadata=metadata or {})
    return {"status": "logged", "event": event}


@mcp.tool()
def log_learning(
    type: str,  # pylint: disable=redefined-builtin
    text: str,
    context_summary: str = "",
    scope: str = "auto",
) -> dict:
    """
    Explicitly record a learning (correction / prod_issue / decision).
    type  : "correction" | "prod_issue" | "decision"
    scope : "project" | "global" | "auto" (auto-detected from text)
    """
    store = get_learning_store()
    metadata = {"context_summary": context_summary}
    result = store.store_learning(type, text, metadata, scope=scope)
    logger.info("mcp.log_learning", extra={"type": type, "scope": result.get("scope")})
    return {"status": "stored", **result}


@mcp.tool()
def retrieve_learnings(
    query: str,
    top_k: int = 5,
    types: list = None,
    scopes: list = None,
) -> list:
    """
    Retrieve learnings (corrections, prod issues, decisions) relevant to query.
    types  : filter list e.g. ["correction", "prod_issue"]
    scopes : ["project", "global"] (default: both)
    """
    store = get_learning_store()
    return store.retrieve_learnings(
        query,
        top_k=top_k,
        types=types or [],
        scopes=scopes or ["project", "global"],
    )


@mcp.tool()
def lookup_symbol(name: str) -> dict:
    """
    Return all locations where a symbol is defined or called,
    with file, line, and type.
    """
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
    from graph.knowledge_graph import EdgeType  # pylint: disable=import-outside-toplevel
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
    return search_episodes(query, limit)


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
        key=graph.G.degree,
        reverse=True,
    )[:5]
    last_indexed = None
    from config.paths import get_path
    ast_index_path = get_path("index/ast_index.json")
    if os.path.exists(ast_index_path):
        with open(ast_index_path, encoding="utf-8") as f:
            last_indexed = json.load(f).get("indexed_at")
    return {
        "node_count": stats["nodes"],
        "edge_count": stats["edges"],
        "top_concepts": top_concepts,
        "last_indexed": last_indexed,
    }


@mcp.tool()
def semantic_search_code(
    query: str,
    top_k: int = 5,
    language: str = None,
) -> list:
    """
    Semantic vector search over indexed code symbols only (no episodic memory
    mixed in).  Optionally filter by language: "python", "typescript", "go", etc.
    """
    return _semantic_search_code(query=query, top_k=top_k, language=language)


@mcp.tool()
def dependency_graph(
    module: str,
    direction: str = "both",
    depth: int = 2,
) -> dict:
    """
    Return import/dependency relationships for a module.
    direction: "imports" | "imported_by" | "both".
    depth: transitive traversal depth (1 = direct only).
    """
    return _dependency_graph(module=module, direction=direction, depth=depth)


@mcp.tool()
def explain_change(
    target: str,
    since: str = "7d",
    max_commits: int = 10,
) -> dict:
    """
    Explain what changed in a file or function recently by cross-referencing
    git history with episodic memory events mentioning the same target.
    """
    return _explain_change(target=target, since=since, max_commits=max_commits)


@mcp.tool()
def context_pack(
    query: str,
    max_tokens: int = 2000,
    include_episodic: bool = True,
    include_symbols: bool = True,
    window_lines: int = 15,
) -> dict:
    """
    Budget-pack the most relevant code + episodic context into a token-bounded
    block ready for injection into the next prompt.  Call this BEFORE reading
    any source file to avoid wasting tokens on raw file reads.
    """
    return _context_pack(
        query=query,
        max_tokens=max_tokens,
        include_episodic=include_episodic,
        include_symbols=include_symbols,
        window_lines=window_lines,
    )


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
                        "source": {
                            "type": "string",
                            "description": "Origin label (file, url, …)",
                            "default": ""
                        },
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
                        "top_k": {
                            "type": "integer",
                            "description": "Number of results",
                            "default": 5
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "search_docs",
                "description": (
                    "Search all markdown documentation files for the given query string."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Text to search for in .md files"
                        },
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
                        "metadata": {
                            "type": "object",
                            "description": "Arbitrary key-value metadata",
                            "default": {}
                        },
                    },
                    "required": ["event"],
                },
            },
            {
                "name": "lookup_symbol",
                "description": (
                    "Return all locations where a symbol is defined or called, "
                    "with file, line, and type."
                ),
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
                        "function_name": {
                            "type": "string",
                            "description": "Name of the function to look up callers for"
                        },
                    },
                    "required": ["function_name"],
                },
            },
            {
                "name": "subgraph",
                "description": (
                    "Return the local neighbourhood of a concept or symbol as {nodes, edges}."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity": {
                            "type": "string",
                            "description": "Entity name or node ID to centre the subgraph on"
                        },
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
                        "query": {
                            "type": "string",
                            "description": "Keyword to search for in event log"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results",
                            "default": 10
                        },
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
            {
                "name": "semantic_search_code",
                "description": "Semantic vector search over code symbols only (no episodic entries).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query":    {"type": "string", "description": "Search query"},
                        "top_k":    {"type": "integer", "default": 5},
                        "language": {"type": "string", "description": "Optional language filter: python, typescript, go, etc.", "default": None},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "dependency_graph",
                "description": "Return import/dependency relationships for a module.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "module":    {"type": "string", "description": "Relative file path"},
                        "direction": {"type": "string", "default": "both", "description": "imports | imported_by | both"},
                        "depth":     {"type": "integer", "default": 2},
                    },
                    "required": ["module"],
                },
            },
            {
                "name": "explain_change",
                "description": "Explain recent changes to a file or function via git + episodic memory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target":      {"type": "string", "description": "File path or function name"},
                        "since":       {"type": "string", "default": "7d", "description": "7d, 30d, or ISO date"},
                        "max_commits": {"type": "integer", "default": 10},
                    },
                    "required": ["target"],
                },
            },
            {
                "name": "context_pack",
                "description": (
                    "Budget-pack the most relevant code + episodic context into a "
                    "token-bounded block for prompt injection.  Call this BEFORE "
                    "reading any source file."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search intent or question"},
                        "max_tokens": {
                            "type": "integer",
                            "description": "Hard token budget for output",
                            "default": 2000,
                        },
                        "include_episodic": {
                            "type": "boolean",
                            "description": "Include episodic memory hits",
                            "default": True,
                        },
                        "include_symbols": {
                            "type": "boolean",
                            "description": "Include AST/symbol hits with code windows",
                            "default": True,
                        },
                        "window_lines": {
                            "type": "integer",
                            "description": "Lines of code context above/below each hit",
                            "default": 15,
                        },
                    },
                    "required": ["query"],
                },
            },
        ],
    }


def _write_manifest() -> None:
    manifest_path = os.path.join(os.path.dirname(__file__), "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(_build_manifest(), f, indent=2)


def run_server(project_dir: str | None = None) -> None:
    """
    Entry point called by the CLI — writes manifest then starts stdio MCP server.

    Parameters
    ----------
    project_dir
        Lock this server instance to a specific project directory.
        When provided, all tools will read/write storage inside *project_dir*.
        When None, defaults to the current working directory (or global storage).

    Project isolation
    -----------------
    Each project should run its own cognirepo MCP server instance.
    Storage defaults to ``~/.cognirepo/storage/<project_hash>/`` to ensure
    isolation between projects even when started without flags.
    """
    from dotenv import load_dotenv  # pylint: disable=import-outside-toplevel
    load_dotenv()
    if project_dir:
        from config.paths import set_cognirepo_dir  # pylint: disable=import-outside-toplevel
        abs_dir = os.path.abspath(project_dir)
        if not os.path.isdir(abs_dir):
            raise SystemExit(f"cognirepo serve: project-dir not found: {abs_dir}")
        cognirepo_subdir = os.path.join(abs_dir, ".cognirepo")
        set_cognirepo_dir(cognirepo_subdir)
    _write_manifest()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
