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
import threading
from mcp.server.fastmcp import FastMCP

from config.logging import setup_logging, new_trace_id
from memory.circuit_breaker import get_breaker, CircuitOpenError

setup_logging()
logger = logging.getLogger(__name__)

from tools.store_memory import store_memory as _store_memory
from tools.retrieve_memory import retrieve_memory as _retrieve_memory
from tools.context_pack import context_pack as _context_pack
from tools.semantic_search_code import semantic_search_code as _semantic_search_code
from tools.dependency_graph import dependency_graph as _dependency_graph
from tools.explain_change import explain_change as _explain_change
from retrieval.docs_search import search_docs as _search_docs
from memory.episodic_memory import log_event, search_episodes
from memory.learning_store import get_learning_store
from memory.embeddings import evict_model
from server.learning_middleware import intercept_after_store, intercept_after_episode
from server.idle_manager import get_idle_manager

_CONFLICT_OVERLAP_THRESHOLD = 0.35  # word-overlap ratio that triggers conflict warning

# ── concurrency gate ──────────────────────────────────────────────────────────
# Limits simultaneous heavy tool ops (embedding + FAISS) to avoid RSS spikes.
# Queue depth = semaphore count; calls block up to _TOOL_ACQUIRE_TIMEOUT seconds.
_TOOL_MAX_CONCURRENT = int(os.environ.get("COGNIREPO_CB_MAX_CONCURRENT", "2"))
_TOOL_ACQUIRE_TIMEOUT = float(os.environ.get("COGNIREPO_CB_ACQUIRE_TIMEOUT_SEC", "10"))
_TOOL_SEMAPHORE = threading.BoundedSemaphore(_TOOL_MAX_CONCURRENT)

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


def _evict_singletons() -> None:
    """Release graph and indexer singletons so they reload on next use."""
    global _GRAPH, _INDEXER  # pylint: disable=global-statement
    if _GRAPH is not None or _INDEXER is not None:
        _GRAPH = None
        _INDEXER = None
        logger.info("idle: graph and indexer evicted from memory")


# ── idle resource manager — evict heavy objects after TTL of inactivity ───────
_idle = get_idle_manager()
_idle.register_evict(evict_model)
_idle.register_evict(_evict_singletons)


# ── auto-store helpers ────────────────────────────────────────────────────────

def _extract_auto_store_text(tool_name: str, result) -> str:
    """
    Extract a storable text summary from a tool result.
    Returns empty string if the result has nothing worth storing.
    """
    try:
        if tool_name == "context_pack" and isinstance(result, dict):
            sections = result.get("sections", [])
            parts = [
                s.get("content", "")
                for s in sections
                if float(s.get("score", 0)) > 0.5 and s.get("content")
            ]
            return "\n\n".join(parts[:5])

        if tool_name == "semantic_search_code" and isinstance(result, list):
            parts = [
                f"{r.get('type','FUNCTION')} {r.get('name','')} in {r.get('file','')}:{r.get('line','')}"
                for r in result if r.get("name")
            ]
            return "\n".join(parts)

        if tool_name == "search_docs" and isinstance(result, list):
            parts = [r.get("snippet") or r.get("text") or "" for r in result if r]
            return "\n\n".join(p for p in parts if p)

        if tool_name == "who_calls" and isinstance(result, list):
            if not result:
                return ""
            callers = [r.get("caller", "") for r in result if r.get("caller")]
            return f"callers: {', '.join(callers[:20])}"

        if tool_name == "subgraph" and isinstance(result, dict):
            nodes = result.get("nodes", [])
            if not nodes:
                return ""
            node_strs = [f"{n.get('type','?')}:{n.get('node_id','')}" for n in nodes[:20]]
            return "subgraph nodes: " + ", ".join(node_strs)

        if tool_name == "dependency_graph" and isinstance(result, dict):
            parts = []
            for key in ("imports", "imported_by", "dependencies"):
                items = result.get(key, [])
                if items:
                    parts.append(f"{key}: {', '.join(str(i) for i in items[:15])}")
            return "\n".join(parts)

        if tool_name == "explain_change" and isinstance(result, dict):
            return result.get("explanation") or result.get("summary") or str(result)

    except Exception:  # pylint: disable=broad-except
        pass
    return ""


def _auto_store_hook(tool_name: str, result) -> None:
    """
    Best-effort auto-store for high-value tool results.
    Runs after the tool returns; never raises; never blocks the caller.
    """
    try:
        text = _extract_auto_store_text(tool_name, result)
        if not text:
            return
        from memory.auto_store import AutoStore  # pylint: disable=import-outside-toplevel
        importance = AutoStore.importance_for(tool_name, result)
        AutoStore().store_if_novel(text, source_tool=tool_name, importance=importance)
    except Exception:  # pylint: disable=broad-except
        pass  # auto-store is always best-effort


_EMPTY_GRAPH_WARNING = {
    "warning": "Graph is empty. Run 'cognirepo index-repo .' first.",
    "results": [],
}


def _graph_is_empty() -> bool:
    return _get_graph().G.number_of_nodes() == 0


def _traced(tool_name: str, fn, *args, **kwargs):
    """
    Run a tool function with:
      1. Circuit-breaker check  — shed load when RSS or storage is over limit
      2. Concurrency gate       — serialise up to _TOOL_MAX_CONCURRENT calls;
                                  extra callers queue (block) for up to
                                  _TOOL_ACQUIRE_TIMEOUT seconds before giving up
      3. Trace logging
    """
    _idle.touch()  # reset idle timer on every tool invocation

    # ── circuit breaker ──────────────────────────────────────────────────────
    try:
        get_breaker().check()
    except CircuitOpenError as exc:
        logger.warning("mcp.tool.shed_load tool=%s reason=%s", tool_name, exc)
        return {"error": str(exc), "shed": True}

    # ── concurrency gate ─────────────────────────────────────────────────────
    acquired = _TOOL_SEMAPHORE.acquire(blocking=True, timeout=_TOOL_ACQUIRE_TIMEOUT)
    if not acquired:
        msg = (
            f"[cognirepo] tool '{tool_name}' timed out waiting for a slot "
            f"(max_concurrent={_TOOL_MAX_CONCURRENT}, "
            f"timeout={_TOOL_ACQUIRE_TIMEOUT:.0f}s). "
            "Retry in a moment or increase COGNIREPO_CB_MAX_CONCURRENT."
        )
        logger.warning("mcp.tool.congestion tool=%s", tool_name)
        return {"error": msg, "shed": True}

    tid = new_trace_id()
    logger.info("mcp.tool.start", extra={"tool": tool_name, "trace_id": tid})
    try:
        result = fn(*args, **kwargs)
        logger.info("mcp.tool.end", extra={"tool": tool_name, "status": "ok"})
        get_breaker().record_success()
        return result
    except Exception:
        logger.exception("mcp.tool.error", extra={"tool": tool_name})
        raise
    finally:
        _TOOL_SEMAPHORE.release()


@mcp.tool()
def store_memory(text: str, source: str = "") -> dict:
    """
    Store a semantic memory with an optional source label.

    The response includes a ``conflicts`` list — existing learnings with high
    word-overlap to the new text.  A non-empty list means a potentially
    contradictory memory already exists; use ``supersede_learning`` to replace
    it rather than letting both co-exist.
    """
    result = _traced("store_memory", _store_memory, text, source)
    # Auto-learning middleware: capture corrections/decisions/prod-issues
    intercept_after_store(text, source=source)
    # Surface conflicts so the agent can decide whether to supersede
    conflicts = get_learning_store().detect_conflicts(text, top_k=3)
    result["conflicts"] = [
        {"id": c.get("id"), "text": c.get("text"), "type": c.get("type")}
        for c in conflicts
    ]
    return result


@mcp.tool()
def retrieve_memory(query: str, top_k: int = 5) -> list:
    """Retrieve the top-k memories most similar to the query."""
    return _traced("retrieve_memory", _retrieve_memory, query, top_k)


@mcp.tool()
def search_docs(query: str) -> list:
    """Search all markdown documentation files for the given query string."""
    result = _search_docs(query)
    _auto_store_hook("search_docs", result)
    return result


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
def deprecate_learning(record_id: str) -> dict:
    """
    Soft-delete a learning by its ID (returned when it was stored).
    Deprecated learnings are excluded from all future retrieve_learnings calls
    but are never physically deleted so the audit trail is preserved.

    Returns ``{"found": bool, "scope": "project"|"global"|null}``.
    """
    store = get_learning_store()
    result = store.deprecate_learning(record_id)
    logger.info("mcp.deprecate_learning", extra={"id": record_id, "found": result.get("found")})
    return result


@mcp.tool()
def supersede_learning(
    old_id: str,
    new_text: str,
    learning_type: str,
    scope: str = "auto",
) -> dict:
    """
    Replace an existing learning with updated content.

    Deprecates the record identified by *old_id* and stores *new_text* as its
    replacement (carrying a ``supersedes`` back-reference).  Use this whenever
    a user corrects or updates a previously recorded decision, bug fix, or
    preference — do NOT call ``store_memory`` again and leave both versions.

    learning_type : "correction" | "prod_issue" | "decision"
    scope         : "project" | "global" | "auto" (default — inferred from text)

    Returns ``{"found_old": bool, "new_id": str, "scope": str}``.
    """
    store = get_learning_store()
    result = store.supersede_learning(
        old_id=old_id,
        new_text=new_text,
        learning_type=learning_type,
        scope=scope,
    )
    logger.info(
        "mcp.supersede_learning",
        extra={"old_id": old_id, "new_id": result.get("new_id"), "scope": result.get("scope")},
    )
    return result


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


def _who_calls_dynamic_fallback(function_name: str) -> list[dict]:
    """
    String-literal grep fallback for dynamic dispatch patterns.
    Finds function_name as a string argument to add_job(), connect(), app.route(), etc.
    Returns hits labelled found_via=dynamic_dispatch_fallback.
    """
    import subprocess  # pylint: disable=import-outside-toplevel
    import re as _re  # pylint: disable=import-outside-toplevel
    from config.paths import get_path  # pylint: disable=import-outside-toplevel

    repo_root = os.environ.get("COGNIREPO_ROOT", os.getcwd())
    results = []
    try:
        # Search for function_name as a string argument in source files
        pattern = rf'["\']?{_re.escape(function_name)}["\']?\s*[,)]'
        proc = subprocess.run(  # nosec B603
            ["grep", "-rn", "--include=*.py", "--include=*.js", "--include=*.ts",
             function_name, repo_root],
            capture_output=True, text=True, timeout=10,
        )
        for line in proc.stdout.splitlines():
            parts = line.split(":", 2)
            if len(parts) < 3:
                continue
            fpath, lineno_s, code = parts
            # Only include lines that look like dynamic registration (not definitions)
            if (f"def {function_name}" in code or f"class {function_name}" in code):
                continue
            # Check for string argument or scheduler/signal patterns
            if (function_name in code and
                    (f'"{function_name}"' in code or f"'{function_name}'" in code or
                     any(kw in code for kw in ["add_job", "connect", "route", "task",
                                               "signal", "register", "handler", "callback"]))):
                try:
                    rel_path = os.path.relpath(fpath, repo_root)
                except ValueError:
                    rel_path = fpath
                results.append({
                    "caller": f"dynamic_dispatch::{rel_path}:{lineno_s}",
                    "file": rel_path,
                    "line": int(lineno_s),
                    "code_snippet": code.strip()[:120],
                    "found_via": "dynamic_dispatch_fallback",
                })
    except Exception:  # pylint: disable=broad-except
        pass
    return results


@mcp.tool()
def who_calls(function_name: str) -> dict:
    """
    Return every caller of a function across the indexed repo.

    First searches the call graph (AST-indexed edges).
    If empty, falls back to string-literal grep for dynamic dispatch patterns
    (APScheduler add_job, Django signals, Flask routes, Celery tasks, etc.).
    Dynamic hits are labelled with found_via=dynamic_dispatch_fallback.
    """
    if _graph_is_empty():
        return _EMPTY_GRAPH_WARNING
    from graph.knowledge_graph import EdgeType  # pylint: disable=import-outside-toplevel
    graph = _get_graph()
    callee_node = f"symbol::{function_name}"
    if not graph.node_exists(callee_node):
        # Try dynamic dispatch fallback immediately — graph has no node at all
        fallback = _who_calls_dynamic_fallback(function_name)
        if fallback:
            return fallback
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
    if not result:
        # Graph has node but no callers — try dynamic dispatch fallback
        fallback = _who_calls_dynamic_fallback(function_name)
        if fallback:
            result = fallback
    _auto_store_hook("who_calls", result)
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
            result = graph.subgraph_around(candidate, radius=depth)
            _auto_store_hook("subgraph", result)
            return result
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
    from graph.knowledge_graph import PYTHON_BUILTINS  # pylint: disable=import-outside-toplevel
    concept_nodes = [
        n for n, d in graph.G.nodes(data=True)
        if d.get("type") == "CONCEPT" and n.split("::")[-1] not in PYTHON_BUILTINS
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
    result = _traced("semantic_search_code", _semantic_search_code, query=query, top_k=top_k, language=language)
    _auto_store_hook("semantic_search_code", result)
    return result


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
    result = _dependency_graph(module=module, direction=direction, depth=depth)
    _auto_store_hook("dependency_graph", result)
    return result


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
    result = _explain_change(target=target, since=since, max_commits=max_commits)
    _auto_store_hook("explain_change", result)
    return result


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
    result = _traced(
        "context_pack",
        _context_pack,
        query=query,
        max_tokens=max_tokens,
        include_episodic=include_episodic,
        include_symbols=include_symbols,
        window_lines=window_lines,
    )
    _auto_store_hook("context_pack", result)
    return result


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
