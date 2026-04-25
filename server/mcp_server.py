# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Real MCP server for CogniRepo — stdio transport, works with Claude Desktop
and any stdio MCP client.
"""
# pylint: disable=duplicate-code
import contextlib
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
_SINGLETON_LOCK = threading.Lock()


def _get_graph():
    """Lazily load KnowledgeGraph (double-checked locking for thread safety)."""
    global _GRAPH  # pylint: disable=global-statement
    if _GRAPH is None:
        with _SINGLETON_LOCK:
            if _GRAPH is None:
                from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
                _GRAPH = KnowledgeGraph()
    return _GRAPH


def _get_indexer():
    """Lazily load ASTIndexer (double-checked locking for thread safety)."""
    global _INDEXER  # pylint: disable=global-statement
    if _INDEXER is None:
        with _SINGLETON_LOCK:
            if _INDEXER is None:
                from indexer.ast_indexer import ASTIndexer  # pylint: disable=import-outside-toplevel
                _INDEXER = ASTIndexer(_get_graph())
                _INDEXER.load()
    return _INDEXER


def _evict_singletons() -> None:
    """Release graph and indexer singletons so they reload on next use."""
    global _GRAPH, _INDEXER  # pylint: disable=global-statement
    with _SINGLETON_LOCK:
        if _GRAPH is not None or _INDEXER is not None:
            _GRAPH = None
            _INDEXER = None
            logger.info("idle: graph and indexer evicted from memory")


@contextlib.contextmanager
def _repo_ctx(repo_path: str | None):
    """
    Context manager that scopes one tool call to a specific repository.

    - repo_path=None  → yields (None, None, None); caller uses module-level singletons
                         and the server's configured cognirepo dir (no change in behaviour).
    - repo_path=<dir> → resolves storage via get_cognirepo_dir_for_repo(), sets _CTX_DIR
                         (thread-safe ContextVar), loads fresh KnowledgeGraph + ASTIndexer
                         for that repo, yields (abs_repo_path, graph, indexer).
                         Singletons are never mutated, preventing cross-repo leaks.
    """
    if repo_path is None:
        yield None, None, None
        return

    from config.paths import _CTX_DIR, get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel
    abs_path = os.path.abspath(repo_path)
    target_dir = get_cognirepo_dir_for_repo(abs_path)
    token = _CTX_DIR.set(target_dir)
    try:
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        from indexer.ast_indexer import ASTIndexer  # pylint: disable=import-outside-toplevel
        g = KnowledgeGraph()
        idx = ASTIndexer(g)
        idx.load()
        yield abs_path, g, idx
    finally:
        _CTX_DIR.reset(token)


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


def _annotate_with_symbol(repo_list: list[dict], symbol: str) -> list[dict]:
    """For each repo entry, add symbol_locations if the symbol exists there."""
    from config.paths import _CTX_DIR, get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel
    for entry in repo_list:
        repo_path = entry.get("repo", "")
        if not repo_path or not os.path.isdir(repo_path):
            continue
        cognirepo_dir = get_cognirepo_dir_for_repo(repo_path)
        if not os.path.isdir(cognirepo_dir):
            continue
        token = _CTX_DIR.set(cognirepo_dir)
        try:
            from indexer.ast_indexer import ASTIndexer  # pylint: disable=import-outside-toplevel
            from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
            idx = ASTIndexer(KnowledgeGraph())
            idx.load()
            locs = idx.lookup_symbol(symbol)
            if locs:
                entry["symbol_locations"] = [
                    {"file": l["file"], "line": l["line"]} for l in locs
                ]
        except Exception:  # pylint: disable=broad-except
            pass
        finally:
            _CTX_DIR.reset(token)
    return repo_list


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
def store_memory(text: str, source: str = "", repo_path: str | None = None) -> dict:
    """
    Store a semantic memory with an optional source label.

    The response includes a ``conflicts`` list — existing learnings with high
    word-overlap to the new text.  A non-empty list means a potentially
    contradictory memory already exists; use ``supersede_learning`` to replace
    it rather than letting both co-exist.

    repo_path: optional absolute path to the target repository. When omitted,
    defaults to the server's configured project directory.
    """
    with _repo_ctx(repo_path):
        result = _traced("store_memory", _store_memory, text, source)
        intercept_after_store(text, source=source)
        conflicts = get_learning_store().detect_conflicts(text, top_k=3)
        result["conflicts"] = [
            {"id": c.get("id"), "text": c.get("text"), "type": c.get("type")}
            for c in conflicts
        ]
    return result


@mcp.tool()
def retrieve_memory(query: str, top_k: int = 5, include_org: bool = False, repo_path: str | None = None) -> list:
    """
    Retrieve the top-k memories most similar to the query.
    If include_org=True, also queries sibling repositories in the same organization.

    repo_path: optional absolute path to the target repository. When omitted,
    defaults to the server's configured project directory.
    """
    with _repo_ctx(repo_path):
        results = _traced("retrieve_memory", _retrieve_memory, query, top_k)

        if include_org:
            from retrieval.cross_repo import CrossRepoRouter  # pylint: disable=import-outside-toplevel
            router = CrossRepoRouter()
            org_results = router.query_org_memories(query, top_k=top_k)
            results.extend(org_results)
            results.sort(key=lambda x: x.get("final_score", x.get("score", 0.0)), reverse=True)
            results = results[:top_k]

    return results


@mcp.tool()
def org_search(query: str, top_k: int = 5) -> list:
    """
    Search for code symbols and memories across all repositories in the organization.
    Returns a list of results annotated with source repository.
    """
    from retrieval.cross_repo import CrossRepoRouter  # pylint: disable=import-outside-toplevel
    router = CrossRepoRouter()
    return router.query_org_memories(query, top_k=top_k)


@mcp.tool()
def org_wide_search(query: str, top_k: int = 5) -> list:
    """
    Search memories across ALL repositories in the organization (every project included).
    Wider than org_search which only covers top-level org repos.
    Prefer cross_repo_search(scope="project") when you only need project-scoped results.

    Claude: use this when the user explicitly asks about org-wide patterns,
    or when project-scoped search returns no results.
    """
    from retrieval.cross_repo import CrossRepoRouter  # pylint: disable=import-outside-toplevel
    router = CrossRepoRouter()
    return router.query_all_org_repos(query, top_k=top_k)


@mcp.tool()
def cross_repo_search(query: str, scope: str = "project", top_k: int = 5) -> dict:
    """
    Search knowledge from sibling repositories.

    scope="project" — only repos in same project (recommended, high relevance).
    scope="org"     — all repos in organization (broader, use sparingly).

    Claude: call this when:
    - lookup_symbol returned empty and the symbol may live in a sibling repo
    - The architecture question spans multiple services in the same project
    - User asks "how does X work across the system" or "what does repo Y do"
    - Importing from a sibling repo and need context on its internals
    """
    from retrieval.cross_repo import CrossRepoRouter  # pylint: disable=import-outside-toplevel
    router = CrossRepoRouter()
    if scope == "project":
        results = router.query_project_memories(query, top_k=top_k)
    else:
        results = router.query_org_memories(query, top_k=top_k)
    return {
        "scope": scope,
        "results": results,
        "project": router._project_name,
        "org": router.org_name,
        "sibling_count": len(router.get_sibling_repos()),
    }


@mcp.tool()
def list_org_context() -> dict:
    """
    Show what org, project, and sibling repositories the current repo belongs to.

    Claude: call this FIRST when the user asks about cross-service or cross-repo topics.
    Use the returned context to decide whether to call cross_repo_search,
    and which scope (project vs org) is appropriate.
    """
    from retrieval.cross_repo import CrossRepoRouter  # pylint: disable=import-outside-toplevel
    router = CrossRepoRouter()
    return router.get_context_summary()


@mcp.tool()
def org_dependencies(depth: int = 2) -> dict:
    """
    Return the bidirectional inter-repo dependency graph for the current organization.

    Shows which services this repo depends on (dependencies) and which services
    depend on this repo (dependents), up to `depth` hops. Edge kinds:
      IMPORTS    — manifest-declared package dependency (auto-detected)
      CALLS_API  — HTTP client calls to another service's endpoint
      SHARES_SCHEMA — shared models/proto repo

    Claude: call this when the user asks about service dependencies,
    "what depends on X", or when investigating cross-service call chains.
    """
    from retrieval.cross_repo import CrossRepoRouter  # pylint: disable=import-outside-toplevel
    from graph.org_graph import get_org_graph  # pylint: disable=import-outside-toplevel

    router = CrossRepoRouter()
    og = get_org_graph()
    current = os.path.abspath(".")

    deps = og.get_dependencies(current, depth=depth)
    dependents = og.get_dependents(current, depth=depth)

    return {
        "current_repo": current,
        "current_repo_name": os.path.basename(current),
        "organization": router.org_name,
        "direct_dependencies": [d for d in deps if d["depth"] == 1],
        "transitive_dependencies": [d for d in deps if d["depth"] > 1],
        "direct_dependents": [d for d in dependents if d["depth"] == 1],
        "transitive_dependents": [d for d in dependents if d["depth"] > 1],
        "graph": og.to_dict(),
    }


@mcp.tool()
def cross_repo_traverse(
    symbol: str | None = None,
    start_repo: str | None = None,
    direction: str = "both",
    depth: int = 2,
) -> dict:
    """
    Traverse the org dependency graph from a repo or symbol to find cross-service
    relationships.

    direction="dependencies" — what does this repo depend on?
    direction="dependents"   — which services depend on this repo?
    direction="both"         — return both directions (default)

    If symbol is provided, also reports where that symbol exists in each traversed repo.

    Claude: use this when the user asks "which services use X?",
    "what does auth-service depend on?", or when tracing a bug across service boundaries.
    """
    from graph.org_graph import get_org_graph  # pylint: disable=import-outside-toplevel

    og = get_org_graph()
    current = os.path.abspath(start_repo) if start_repo else os.path.abspath(".")

    result: dict = {
        "start_repo": current,
        "start_repo_name": os.path.basename(current),
        "direction": direction,
        "depth": depth,
    }

    if direction in ("dependencies", "both"):
        deps = og.get_dependencies(current, depth=depth)
        if symbol:
            deps = _annotate_with_symbol(deps, symbol)
        result["dependencies"] = deps

    if direction in ("dependents", "both"):
        dependents = og.get_dependents(current, depth=depth)
        if symbol:
            dependents = _annotate_with_symbol(dependents, symbol)
        result["dependents"] = dependents

    if symbol:
        result["symbol"] = symbol

    return result


@mcp.tool()
def lookup_symbol(name: str, include_org: bool = False, repo_path: str | None = None) -> list:
    """
    Return all locations where a symbol is defined or called,
    with file, line, and type.
    If include_org=True, also searches sibling repositories in the same organization.

    repo_path: optional absolute path to the target repository. When omitted,
    defaults to the server's configured project directory.
    """
    with _repo_ctx(repo_path) as (_root, g, idx):
        if g is None:
            if _graph_is_empty():
                return _EMPTY_GRAPH_WARNING
            idx = _get_indexer()
        else:
            if g.G.number_of_nodes() == 0:
                return _EMPTY_GRAPH_WARNING

        locations = idx.lookup_symbol(name)
        result = []
        for loc in locations:
            file_path = loc["file"]
            line = loc["line"]
            sym_type = "UNKNOWN"
            file_data = idx.index_data["files"].get(file_path, {})
            for sym in file_data.get("symbols", []):
                if sym["name"] == name and sym["start_line"] == line:
                    sym_type = sym["type"]
                    break
            result.append({"file": file_path, "line": line, "type": sym_type, "repo": "local"})

        if include_org:
            from retrieval.cross_repo import CrossRepoRouter  # pylint: disable=import-outside-toplevel
            from indexer.ast_indexer import ASTIndexer  # pylint: disable=import-outside-toplevel
            from config.paths import _CTX_DIR, get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel

            router = CrossRepoRouter()
            for repo in router.get_sibling_repos():
                cognirepo_dir = get_cognirepo_dir_for_repo(repo)
                if not os.path.isdir(cognirepo_dir):
                    continue
                sib_token = _CTX_DIR.set(cognirepo_dir)
                try:
                    from graph.knowledge_graph import KnowledgeGraph as _KG  # pylint: disable=import-outside-toplevel
                    sib_indexer = ASTIndexer(_KG())
                    sib_indexer.load()
                    sib_locs = sib_indexer.lookup_symbol(name)
                    for sl in sib_locs:
                        sl["repo"] = os.path.basename(repo)
                        result.append(sl)
                except Exception:  # pylint: disable=broad-except
                    pass
                finally:
                    _CTX_DIR.reset(sib_token)

    return result


@mcp.tool()
def search_token(word: str, repo_path: str | None = None) -> dict:
    """
    Word-level reverse-index search.

    Unlike lookup_symbol() which only matches defined symbol names,
    search_token() finds any word that appears in symbol names,
    docstrings, or inline comments across the indexed codebase.

    Examples:
      search_token("background")  → files containing 'background' in names/docs
      search_token("validate")    → all functions whose docs mention validation
      search_token("github")      → files where GitHub is referenced in comments

    Returns a list of {file, line} dicts sorted by file path.

    repo_path: optional absolute path to the target repository.
    """
    with _repo_ctx(repo_path) as (_root, _g, idx):
        if idx is None:
            idx = _get_indexer()
        locations = idx.lookup_word(word.lower().strip())
    if not locations:
        return {"results": [], "count": 0, "word": word}
    return {"results": locations, "count": len(locations), "word": word}


def _who_calls_dynamic_fallback(function_name: str, repo_root: str | None = None) -> list[dict]:
    """
    String-literal grep fallback for dynamic dispatch patterns.
    Finds function_name as a string argument to add_job(), connect(), app.route(), etc.
    Returns hits labelled found_via=dynamic_dispatch_fallback.
    """
    import subprocess  # pylint: disable=import-outside-toplevel
    import re as _re  # pylint: disable=import-outside-toplevel

    repo_root = repo_root or os.environ.get("COGNIREPO_ROOT", os.getcwd())
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
    except Exception as _exc:  # pylint: disable=broad-except
        import logging as _logging  # pylint: disable=import-outside-toplevel
        _logging.getLogger(__name__).warning("who_calls grep fallback failed: %s", _exc)
    return results


@mcp.tool()
def who_calls(function_name: str, repo_path: str | None = None) -> dict:
    """
    Return every caller of a function across the indexed repo.

    First searches the call graph (AST-indexed edges).
    If empty, falls back to string-literal grep for dynamic dispatch patterns
    (APScheduler add_job, Django signals, Flask routes, Celery tasks, etc.).
    Dynamic hits are labelled with found_via=dynamic_dispatch_fallback.

    repo_path: optional absolute path to the target repository.
    """
    with _repo_ctx(repo_path) as (repo_root, g, _idx):
        if g is None:
            if _graph_is_empty():
                return _EMPTY_GRAPH_WARNING
            g = _get_graph()
        else:
            if g.G.number_of_nodes() == 0:
                return _EMPTY_GRAPH_WARNING

        from graph.knowledge_graph import EdgeType  # pylint: disable=import-outside-toplevel
        callee_node = f"symbol::{function_name}"
        if not g.node_exists(callee_node):
            fallback = _who_calls_dynamic_fallback(function_name, repo_root)
            if fallback:
                return fallback
            return []
        result = []
        for caller in g.G.successors(callee_node):
            edge_data = g.G[callee_node][caller]
            if edge_data.get("rel") == EdgeType.CALLS:
                node_data = dict(g.G.nodes[caller])
                result.append({
                    "caller": caller,
                    "file": node_data.get("file", ""),
                    "line": node_data.get("line", -1),
                    "source": "graph",
                })
        if not result:
            for caller in g.G.predecessors(callee_node):
                edge_data = g.G[caller][callee_node]
                if edge_data.get("rel") == EdgeType.CALLED_BY:
                    node_data = dict(g.G.nodes[caller])
                    result.append({
                        "caller": caller,
                        "file": node_data.get("file", ""),
                        "line": node_data.get("line", -1),
                        "source": "graph_legacy",
                    })
        if not result:
            fallback = _who_calls_dynamic_fallback(function_name, repo_root)
            if fallback:
                result = fallback

        # Cross-repo: check dependent services for callers of this function
        cross_repo_callers: list[dict] = []
        try:
            from graph.org_graph import get_org_graph  # pylint: disable=import-outside-toplevel
            from config.paths import _CTX_DIR, get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel
            og = get_org_graph()
            current = os.path.abspath(repo_root or ".")
            dependents = og.get_dependents(current, depth=1)
            for dep in dependents:
                dep_repo = dep["repo"]
                cog_dir = get_cognirepo_dir_for_repo(dep_repo)
                if not os.path.isdir(cog_dir):
                    continue
                token = _CTX_DIR.set(cog_dir)
                try:
                    from indexer.ast_indexer import ASTIndexer  # pylint: disable=import-outside-toplevel
                    from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
                    sib_idx = ASTIndexer(KnowledgeGraph())
                    sib_idx.load()
                    for loc in sib_idx.lookup_symbol(function_name):
                        cross_repo_callers.append({
                            "caller": function_name,
                            "repo": dep_repo,
                            "repo_name": os.path.basename(dep_repo),
                            "file": loc["file"],
                            "line": loc["line"],
                            "source": "cross_repo",
                        })
                except Exception:  # pylint: disable=broad-except
                    pass
                finally:
                    _CTX_DIR.reset(token)
        except Exception:  # pylint: disable=broad-except
            pass

        _auto_store_hook("who_calls", result)

    if cross_repo_callers:
        return {"local_callers": result, "cross_repo_callers": cross_repo_callers}
    return result


@mcp.tool()
def subgraph(entity: str, depth: int = 2, repo_path: str | None = None) -> dict:
    """
    Return the local neighbourhood of a concept or symbol as {nodes, edges}.

    repo_path: optional absolute path to the target repository.
    """
    with _repo_ctx(repo_path) as (_root, g, _idx):
        if g is None:
            if _graph_is_empty():
                return _EMPTY_GRAPH_WARNING
            g = _get_graph()
        else:
            if g.G.number_of_nodes() == 0:
                return _EMPTY_GRAPH_WARNING
        candidates = [entity, f"symbol::{entity}", f"concept::{entity.lower()}"]
        for candidate in candidates:
            if g.node_exists(candidate):
                result = g.subgraph_around(candidate, radius=depth)
                _auto_store_hook("subgraph", result)
                return result
    return {"nodes": [], "edges": []}


@mcp.tool()
def episodic_search(query: str, limit: int = 10, repo_path: str | None = None) -> list:
    """
    Return past episodic events matching a keyword query.

    repo_path: optional absolute path to the target repository.
    """
    with _repo_ctx(repo_path):
        return search_episodes(query, limit)


@mcp.tool()
def graph_stats(repo_path: str | None = None) -> dict:
    """
    Return a health summary of the current graph state.

    repo_path: optional absolute path to the target repository.
    """
    with _repo_ctx(repo_path) as (_root, g, _idx):
        if g is None:
            g = _get_graph()
        stats = g.stats()
        from graph.knowledge_graph import PYTHON_BUILTINS  # pylint: disable=import-outside-toplevel
        concept_nodes = [
            n for n, d in g.G.nodes(data=True)
            if d.get("type") == "CONCEPT" and n.split("::")[-1] not in PYTHON_BUILTINS
        ]
        top_concepts = sorted(concept_nodes, key=g.G.degree, reverse=True)[:5]
        last_indexed = None
        from config.paths import get_path  # pylint: disable=import-outside-toplevel
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
    repo_path: str | None = None,
) -> list:
    """
    Semantic vector search over indexed code symbols only (no episodic memory
    mixed in).  Optionally filter by language: "python", "typescript", "go", etc.

    repo_path: optional absolute path to the target repository.
    """
    with _repo_ctx(repo_path):
        result = _traced("semantic_search_code", _semantic_search_code, query=query, top_k=top_k, language=language)
        _auto_store_hook("semantic_search_code", result)
    return result


@mcp.tool()
def dependency_graph(
    module: str,
    direction: str = "both",
    depth: int = 2,
    repo_path: str | None = None,
) -> dict:
    """
    Return import/dependency relationships for a module.
    direction: "imports" | "imported_by" | "both".
    depth: transitive traversal depth (1 = direct only).

    repo_path: optional absolute path to the target repository.
    """
    with _repo_ctx(repo_path):
        result = _dependency_graph(module=module, direction=direction, depth=depth)
        _auto_store_hook("dependency_graph", result)
    return result


@mcp.tool()
def explain_change(
    target: str,
    since: str = "7d",
    max_commits: int = 10,
    repo_path: str | None = None,
) -> dict:
    """
    Explain what changed in a file or function recently by cross-referencing
    git history with episodic memory events mentioning the same target.

    repo_path: optional absolute path to the target repository.
    """
    with _repo_ctx(repo_path):
        result = _explain_change(target=target, since=since, max_commits=max_commits)
        _auto_store_hook("explain_change", result)
    return result


@mcp.tool()
def architecture_overview(scope: str = "root", repo_path: str | None = None) -> str:
    """
    Retrieve pre-computed architectural summaries.
    scope: 'root' for repo summary, a directory path, or a file path.

    repo_path: optional absolute path to the target repository.
    """
    with _repo_ctx(repo_path):
        from config.paths import get_path  # pylint: disable=import-outside-toplevel
        summary_path = get_path("index/summaries.json")
        if not os.path.exists(summary_path):
            return "Summaries not found. Ask the user to run 'cognirepo summarize' first."

        with open(summary_path, "r", encoding="utf-8") as f:
            data = json.load(f)

    if scope == "root":
        return data.get("repo", "No repository summary available.")
    if scope in data.get("directories", {}):
        return data["directories"][scope]
    if scope in data.get("files", {}):
        return data["files"][scope]
    return f"No summary found for scope: {scope}"


@mcp.tool()
def context_pack(
    query: str,
    max_tokens: int = 2000,
    include_episodic: bool = True,
    include_symbols: bool = True,
    window_lines: int = 15,
    repo_path: str | None = None,
) -> dict:
    """
    Budget-pack the most relevant code + episodic context into a token-bounded
    block ready for injection into the next prompt.  Call this BEFORE reading
    any source file to avoid wasting tokens on raw file reads.

    repo_path: optional absolute path to the target repository. When omitted,
    defaults to the server's configured project directory.
    """
    with _repo_ctx(repo_path) as (repo_root, _g, _idx):
        result = _traced(
            "context_pack",
            _context_pack,
            query=query,
            max_tokens=max_tokens,
            include_episodic=include_episodic,
            include_symbols=include_symbols,
            window_lines=window_lines,
            repo_root=repo_root,
        )
        _auto_store_hook("context_pack", result)
    return result


@mcp.tool()
def get_session_history(limit: int = 10, repo_path: str | None = None) -> list:
    """
    Return recent conversation session exchanges for context continuity.

    Each entry has: session_id, created_at, message_count, and last_exchange
    (the final user/assistant pair).  Call at session start to resume context.

    limit: number of most-recent sessions to return (default 10).
    repo_path: optional absolute path to the target repository.
    """
    with _repo_ctx(repo_path):
        from config.paths import get_path as _gp  # pylint: disable=import-outside-toplevel
        import glob  # pylint: disable=import-outside-toplevel
        sessions_dir = _gp("sessions")
        if not os.path.isdir(sessions_dir):
            return []
        session_files = sorted(
            glob.glob(os.path.join(sessions_dir, "*.json")),
            key=os.path.getmtime,
            reverse=True,
        )
        # exclude the "current.json" pointer file
        session_files = [f for f in session_files if not f.endswith("current.json")]
        results = []
        for sf in session_files[:limit]:
            try:
                with open(sf, encoding="utf-8") as f:
                    data = json.load(f)
                messages = data.get("messages", [])
                # get last user/assistant exchange
                last_exchange = {}
                for i in range(len(messages) - 1, -1, -1):
                    if messages[i].get("role") == "assistant":
                        last_exchange["assistant"] = messages[i].get("content", "")[:300]
                    elif messages[i].get("role") == "user" and "assistant" in last_exchange:
                        last_exchange["user"] = messages[i].get("content", "")[:300]
                        break
                results.append({
                    "session_id": data.get("session_id", os.path.basename(sf)),
                    "created_at": data.get("created_at"),
                    "message_count": len(messages),
                    "model": data.get("model", "unknown"),
                    "last_exchange": last_exchange,
                })
            except (OSError, json.JSONDecodeError):
                continue
    return results


@mcp.tool()
def get_user_profile(repo_path: str | None = None) -> dict:
    """
    Return the user's interaction style profile for Claude to adapt its responses.

    Includes: depth preference, dominant question types, domain vocabulary,
    code-focus percentage, and framing hints Claude should apply.

    Call this at the start of a session to calibrate response style.

    repo_path: optional absolute path to the target repository.
    """
    with _repo_ctx(repo_path) as (_root, g, _idx):
        if g is None:
            g = _get_graph()
        from graph.behaviour_tracker import BehaviourTracker  # pylint: disable=import-outside-toplevel
        bt = BehaviourTracker(g)
    return bt.get_user_profile()


@mcp.tool()
def get_error_patterns(min_count: int = 1, repo_path: str | None = None) -> list:
    """
    Return recurring error patterns with prevention hints to avoid repeating mistakes.

    Each entry has: error_type, count, affected files, last_seen, prevention_hint,
    and the most recent error message for context.

    Use this to guide Claude away from solutions that have historically failed.

    min_count: only return errors seen at least this many times (default 1).
    repo_path: optional absolute path to the target repository.
    """
    with _repo_ctx(repo_path) as (_root, g, _idx):
        if g is None:
            g = _get_graph()
        from graph.behaviour_tracker import BehaviourTracker  # pylint: disable=import-outside-toplevel
        bt = BehaviourTracker(g)
    return bt.get_error_patterns(min_count=min_count)


@mcp.tool()
def record_error(
    error_type: str,
    message: str = "",
    file_path: str = "",
    query_context: str = "",
    repo_path: str | None = None,
) -> dict:
    """
    Record an error Claude or the user encountered so future sessions can avoid it.

    error_type: exception class name or short label (e.g. "TypeError", "build_failed").
    message: error message text (truncated to 300 chars).
    file_path: source file where the error occurred (optional).
    query_context: the query or action that triggered the error (optional).
    repo_path: optional absolute path to the target repository.

    Returns: the prevention hint for this error type.
    """
    with _repo_ctx(repo_path) as (_root, g, _idx):
        if g is None:
            g = _get_graph()
        from graph.behaviour_tracker import BehaviourTracker  # pylint: disable=import-outside-toplevel
        bt = BehaviourTracker(g)
        bt.record_error(
            error_type=error_type,
            file_path=file_path,
            message=message,
            query_context=query_context,
        )
        bt.save()
        patterns = bt.get_error_patterns()
        hint = next(
            (p["prevention_hint"] for p in patterns if p["error_type"] == error_type),
            "Track root cause and add a guard at the call site.",
        )
    return {"recorded": True, "error_type": error_type, "prevention_hint": hint}


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
                        "repo_path": {
                            "type": "string",
                            "description": "Absolute path to target repository (optional, defaults to server's project dir)",
                            "default": None,
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
                        "include_org": {
                            "type": "boolean",
                            "description": "Search across all repos in the organization",
                            "default": False
                        },
                        "repo_path": {
                            "type": "string",
                            "description": "Absolute path to target repository (optional)",
                            "default": None,
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "org_search",
                "description": "Semantic search across all repositories in the organization.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "top_k": {"type": "integer", "default": 5},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "org_dependencies",
                "description": "List all repositories linked within the same local organization.",
                "parameters": {
                    "type": "object",
                    "properties": {},
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
                        "include_org": {
                            "type": "boolean",
                            "description": "Search across sibling repos in the organization",
                            "default": False
                        },
                        "repo_path": {
                            "type": "string",
                            "description": "Absolute path to target repository (optional)",
                            "default": None,
                        },
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
                        "repo_path": {
                            "type": "string",
                            "description": "Absolute path to target repository (optional)",
                            "default": None,
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
                        "repo_path": {
                            "type": "string",
                            "description": "Absolute path to target repository (optional)",
                            "default": None,
                        },
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
                        "repo_path": {
                            "type": "string",
                            "description": "Absolute path to target repository (optional)",
                            "default": None,
                        },
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
                "name": "architecture_overview",
                "description": "Retrieve pre-computed high-level architectural summaries.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "scope": {
                            "type": "string",
                            "description": "Scope: 'root' for repo, a directory path, or a file path.",
                            "default": "root"
                        },
                    },
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
                        "repo_path": {
                            "type": "string",
                            "description": "Absolute path to target repository (optional, defaults to server's project dir)",
                            "default": None,
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
        from config.paths import (  # pylint: disable=import-outside-toplevel
            set_cognirepo_dir, get_cognirepo_dir_for_repo,
        )
        abs_dir = os.path.abspath(project_dir)
        if not os.path.isdir(abs_dir):
            raise SystemExit(f"cognirepo serve: project-dir not found: {abs_dir}")
        # Resolve correctly: use local .cognirepo/ if present, else global fallback.
        resolved_dir = get_cognirepo_dir_for_repo(abs_dir)
        set_cognirepo_dir(resolved_dir)
        # Discard any singleton loaded before the dir was set.
        _evict_singletons()
        logger.info("run_server: project_dir=%s resolved_cognirepo=%s", abs_dir, resolved_dir)
    # ── auto-start file watcher (background daemon, keeps index fresh) ────────
    try:
        _watch_cfg: dict = {}
        from config.paths import get_path as _get_path  # pylint: disable=import-outside-toplevel
        _cfg_path = _get_path("config.json")
        if os.path.exists(_cfg_path):
            with open(_cfg_path, encoding="utf-8") as _wf:
                _watch_cfg = json.load(_wf).get("watch", {})
        if _watch_cfg.get("auto_enabled", True):
            from cli.main import _start_watcher_bg  # pylint: disable=import-outside-toplevel
            _start_watcher_bg(project_dir or os.getcwd())
    except Exception:  # pylint: disable=broad-except
        pass  # watcher is best-effort — never block server startup

    _write_manifest()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
