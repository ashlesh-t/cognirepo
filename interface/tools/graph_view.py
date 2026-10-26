# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Read-only knowledge-graph view for the control API.

Single entry point for graph reads from the UI (CLAUDE.md: route handlers never touch the
graph directly). Strictly read-only: it never calls ``save()`` / ``begin_journal()`` and
exposes only whitelisted node/edge attributes, with server-side bounds on every query so the
full graph is never serialised.
"""
from __future__ import annotations

import gc
import threading
import time
from typing import Any

MAX_LIMIT = 2000
MAX_DEPTH = 3
_IDLE_TTL_S = 120.0

_NODE_KEYS = ("type", "file", "line", "unresolved", "ambiguous", "dispatch")
_EDGE_KEYS = ("rel", "weight")

_MAX_CACHED = 2          # graphs held at once (the served repo plus one other): each can be large
_lock = threading.Lock()
_cache: dict[str, dict[str, Any]] = {}     # store dir ("" = the served repo) -> {"kg", "used"}


def _graph(store: str | None = None):
    """Lazily load a repo's graph; drop it after an idle TTL so the UI process stays light.

    ``store`` is another repo's ``.cognirepo`` directory (selected via ``?repo=``). The graph file path is
    resolved through a ContextVar, so loading and reloading happen inside that repo's context; reads after
    that only touch the in-memory graph."""
    from data.graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
    from core.config.paths import _CTX_DIR  # pylint: disable=import-outside-toplevel
    key = store or ""
    now = time.monotonic()
    with _lock:
        for k in [k for k, v in _cache.items() if now - v["used"] > _IDLE_TTL_S]:
            del _cache[k]
            gc.collect()
        entry = _cache.get(key)
        token = _CTX_DIR.set(store) if store else None
        try:
            if entry is None:
                entry = _cache[key] = {"kg": KnowledgeGraph(), "used": now}
                while len(_cache) > _MAX_CACHED:
                    oldest = min((k for k in _cache if k != key), key=lambda k: _cache[k]["used"])
                    del _cache[oldest]
                    gc.collect()
            else:
                from data.graph.backend import is_current  # pylint: disable=import-outside-toplevel
                if not is_current(entry["kg"]):
                    entry["kg"] = KnowledgeGraph()
                else:
                    entry["kg"].reload_if_changed()
        finally:
            if token is not None:
                _CTX_DIR.reset(token)
        entry["used"] = now
        return entry["kg"]


def reset_cache() -> None:
    """Drop every cached graph (tests, and after the idle TTL)."""
    with _lock:
        _cache.clear()
    gc.collect()


def _node(graph, node_id: str) -> dict[str, Any]:
    data = graph.node_attrs(node_id)
    out: dict[str, Any] = {"id": node_id}
    for key in _NODE_KEYS:
        if key in data:
            out[key] = data[key]
    return out


def _edge(u: str, v: str, data: dict) -> dict[str, Any]:
    out: dict[str, Any] = {"source": u, "target": v}
    for key in _EDGE_KEYS:
        if key in data:
            out[key] = data[key]
    return out


def graph_view(node: str | None = None, depth: int = 1, limit: int = 200,
               store: str | None = None) -> dict[str, Any]:
    """Bounded slice of the knowledge graph.

    ``node`` given: neighbourhood within ``depth`` hops (<= 3), at most ``limit`` nodes.
    ``node`` omitted: overview = the ``limit`` highest-degree nodes and edges among them.
    ``store``: another repo's ``.cognirepo`` directory (the control API resolves it from the registry);
    omitted = the repo this process is serving.
    """
    depth = max(0, min(int(depth), MAX_DEPTH))
    limit = max(1, min(int(limit), MAX_LIMIT))
    kg = _graph(store)
    stats = kg.stats()
    result: dict[str, Any] = {"stats": stats, "root": node, "found": True, "truncated": False,
                              "nodes": [], "edges": []}
    if node is not None:
        if not kg.node_exists(node):
            result["found"] = False
            return result
        sub = kg.subgraph_around(node, radius=depth, max_nodes=limit, max_edges=limit * 3)
        ids = [n["node_id"] for n in sub.get("nodes", []) if kg.node_exists(n.get("node_id"))]
        result["truncated"] = bool(sub.get("truncated", False))
        edge_pairs = [(e.get("source"), e.get("target")) for e in sub.get("edges", [])]
    else:
        ids = kg.top_degree_ids(limit + 1)
        result["truncated"] = len(ids) > limit
        ids = ids[:limit]
        keep = set(ids)
        edge_pairs = [(u, v) for u in ids for v in kg.successors(u) if v in keep][: limit * 3]
    result["nodes"] = [_node(kg, n) for n in ids]
    result["edges"] = [_edge(u, v, kg.edge_data(u, v) or {}) for u, v in edge_pairs if kg.has_edge(u, v)]
    return result
