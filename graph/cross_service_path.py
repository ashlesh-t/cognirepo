# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""
graph/cross_service_path.py
Cross-service shortest-path finder (multi-graph Dijkstra).

Finds the shortest symbol-level path between any two symbols,
crossing service boundaries when necessary:

  local KG (service A) → org edge A→B → local KG (service B) → ...

Uses nx.dijkstra_path with inverse-weight edge costs:
  w=1.0 (direct entry-point) → cost=1
  w=0.75 (hop-2 reachable)   → cost=1.3
  w=0.5  (indirect)          → cost=2.0
  org CALLS_API edge          → cost=5  (prefer staying in one service)
"""
from __future__ import annotations

import logging
import os
from typing import Any

import networkx as nx

log = logging.getLogger(__name__)

# Edge cost by symbol crawl weight
_WEIGHT_TO_COST: dict[float, float] = {1.0: 1.0, 0.75: 1.3, 0.5: 2.0}
_DEFAULT_COST = 2.0
_CROSS_SERVICE_COST = 5.0


def _weight_cost(w: float) -> float:
    for threshold, cost in sorted(_WEIGHT_TO_COST.items(), reverse=True):
        if w >= threshold:
            return cost
    return _DEFAULT_COST


def _load_kg(repo_abs: str) -> "nx.DiGraph | None":
    """Load the KnowledgeGraph for a given repo directory."""
    try:
        from core.config.paths import _CTX_DIR, get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        sib_dir = get_cognirepo_dir_for_repo(repo_abs)
        token = _CTX_DIR.set(sib_dir)
        try:
            kg = KnowledgeGraph()
            return kg.G
        finally:
            _CTX_DIR.reset(token)
    except Exception as exc:  # pylint: disable=broad-except
        log.debug("cross_service_path: could not load KG for %s: %s", repo_abs, exc)
        return None


def _find_symbol_in_repo(symbol: str, repo_abs: str) -> "str | None":
    """Return the KG node ID for symbol in repo_abs, or None."""
    try:
        from core.config.paths import _CTX_DIR, get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel
        from indexer.ast_indexer import ASTIndexer  # pylint: disable=import-outside-toplevel
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        sib_dir = get_cognirepo_dir_for_repo(repo_abs)
        token = _CTX_DIR.set(sib_dir)
        try:
            idx = ASTIndexer(KnowledgeGraph())
            idx.load()
            locs = idx.lookup_symbol(symbol)
            if locs:
                from graph.graph_utils import make_node_id  # pylint: disable=import-outside-toplevel
                return make_node_id("FUNCTION", symbol, locs[0]["file"])
        finally:
            _CTX_DIR.reset(token)
    except Exception as exc:  # pylint: disable=broad-except
        log.debug("cross_service_path: lookup %s in %s failed: %s", symbol, repo_abs, exc)
    return None


def _build_local_subgraph(G: "nx.DiGraph", cost_attr: str = "kg_cost") -> "nx.DiGraph":
    """Return a weighted copy of KG with Dijkstra-friendly costs on edges."""
    weighted = nx.DiGraph()
    for u, v, data in G.edges(data=True):
        w = data.get("weight", 0.5)
        cost = _weight_cost(w)
        weighted.add_edge(u, v, **{cost_attr: cost})
    return weighted


def find_symbol_path(
    from_symbol: str,
    to_symbol: str,
    from_repo: str | None = None,
    to_repo: str | None = None,
) -> dict[str, Any]:
    """
    Find the shortest path between two symbols, crossing service boundaries
    via the org graph when needed.

    Parameters
    ----------
    from_symbol : Name of the source symbol.
    to_symbol   : Name of the destination symbol.
    from_repo   : Absolute path to the source repo (auto-detected if omitted).
    to_repo     : Absolute path to the destination repo (auto-detected if omitted).

    Returns
    -------
    dict with keys:
      path              — list of annotated step dicts
      hops              — total hop count
      crosses_services  — True if path spans multiple services
      services_traversed— list of service names
      error             — error message if path not found
    """
    from graph.org_graph import get_org_graph  # pylint: disable=import-outside-toplevel
    from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel

    og = get_org_graph()

    # ── Locate symbols ────────────────────────────────────────────────────────
    cwd = os.getcwd()
    _from_repo = os.path.abspath(from_repo) if from_repo else cwd
    _to_repo = os.path.abspath(to_repo) if to_repo else cwd

    # If repos not specified, search across org
    if not from_repo or not to_repo:
        from retrieval.cross_repo import CrossRepoRouter  # pylint: disable=import-outside-toplevel
        router = CrossRepoRouter()
        all_repos = [cwd] + router.get_sibling_repos()
        for repo in all_repos:
            if not from_repo:
                node = _find_symbol_in_repo(from_symbol, repo)
                if node:
                    _from_repo = repo
            if not to_repo:
                node = _find_symbol_in_repo(to_symbol, repo)
                if node:
                    _to_repo = repo
            if from_repo and to_repo:
                break

    from_node = _find_symbol_in_repo(from_symbol, _from_repo)
    to_node = _find_symbol_in_repo(to_symbol, _to_repo)

    if not from_node:
        return {"error": f"Symbol '{from_symbol}' not found in indexed repos", "path": [], "hops": -1}
    if not to_node:
        return {"error": f"Symbol '{to_symbol}' not found in indexed repos", "path": [], "hops": -1}

    # ── Same repo: pure KG shortest path ─────────────────────────────────────
    if _from_repo == _to_repo:
        kg_g = _load_kg(_from_repo)
        if kg_g is None:
            return {"error": "Could not load knowledge graph", "path": [], "hops": -1}
        try:
            raw_path = nx.shortest_path(kg_g, from_node, to_node)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            # Try undirected fallback
            try:
                raw_path = nx.shortest_path(kg_g.to_undirected(), from_node, to_node)
            except Exception:  # pylint: disable=broad-except
                return {"error": f"No path between '{from_symbol}' and '{to_symbol}'", "path": [], "hops": -1}
        path_steps = [
            {"node": n, "repo": os.path.basename(_from_repo), "repo_path": _from_repo, "type": "local"}
            for n in raw_path
        ]
        return {
            "path": path_steps,
            "hops": len(path_steps) - 1,
            "crosses_services": False,
            "services_traversed": [os.path.basename(_from_repo)],
        }

    # ── Cross-service: org graph repo path + per-repo KG traversal ───────────
    org_repo_path = og.shortest_path(_from_repo, _to_repo)
    if not org_repo_path:
        return {
            "error": (
                f"No org-graph path between '{os.path.basename(_from_repo)}' "
                f"and '{os.path.basename(_to_repo)}'. "
                "Link the repos first: cognirepo org link <src> <dst>"
            ),
            "path": [], "hops": -1,
        }

    full_path: list[dict] = []
    services_traversed: list[str] = []
    total_hops = 0

    for hop_idx, repo in enumerate(org_repo_path):
        kg_g = _load_kg(repo)
        svc_name = os.path.basename(repo)
        services_traversed.append(svc_name)

        if kg_g is None:
            full_path.append({"node": f"[{svc_name}]", "repo": svc_name, "repo_path": repo, "type": "service_stub"})
            continue

        # Entry point into this service's KG
        if hop_idx == 0:
            entry_node = from_node
        else:
            # Find the function that receives the call from the previous service
            # (look for CALLS_ENDPOINT edges incoming to this service)
            entry_node = _find_entry_node(kg_g, org_repo_path[hop_idx - 1], repo)

        # Exit point from this service's KG
        if hop_idx == len(org_repo_path) - 1:
            exit_node = to_node
        else:
            # Find the function in this service that calls the next service
            exit_node = _find_exit_node(kg_g, repo, org_repo_path[hop_idx + 1])

        # Local KG path from entry to exit
        local_steps: list[str] = []
        if entry_node and exit_node and entry_node != exit_node:
            try:
                local_steps = nx.shortest_path(kg_g, entry_node, exit_node)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                try:
                    local_steps = nx.shortest_path(kg_g.to_undirected(), entry_node, exit_node)
                except Exception:  # pylint: disable=broad-except
                    local_steps = [entry_node, exit_node] if entry_node and exit_node else []
        elif entry_node:
            local_steps = [entry_node]

        for node in local_steps:
            full_path.append({"node": node, "repo": svc_name, "repo_path": repo, "type": "local"})
        total_hops += max(0, len(local_steps) - 1)

        # Add org-edge marker between services
        if hop_idx < len(org_repo_path) - 1:
            next_svc = os.path.basename(org_repo_path[hop_idx + 1])
            edge_data = og.G.get_edge_data(repo, org_repo_path[hop_idx + 1], default={})
            ep_pattern = edge_data.get("endpoint_pattern", "")
            full_path.append({
                "node": f"→ {next_svc}{ep_pattern}",
                "type": "org_edge",
                "kind": edge_data.get("kind", "CALLS_API"),
                "endpoint_pattern": ep_pattern,
            })
            total_hops += 1

    return {
        "path": full_path,
        "hops": total_hops,
        "crosses_services": True,
        "services_traversed": services_traversed,
    }


def _find_entry_node(kg_g: "nx.DiGraph", prev_repo: str, this_repo: str) -> "str | None":
    """Find the ENDPOINT node in kg_g that receives calls from prev_repo."""
    ep_prefix = f"endpoint::{this_repo}::"
    for node in kg_g.nodes:
        if node.startswith(ep_prefix):
            return node
    # Fallback: any node with ENDPOINT type
    for node, data in kg_g.nodes(data=True):
        if data.get("type") == "ENDPOINT" or "ENDPOINT" in str(data.get("node_type", "")):
            return node
    return None


def _find_exit_node(kg_g: "nx.DiGraph", this_repo: str, next_repo: str) -> "str | None":
    """Find the function node in kg_g that CALLS_ENDPOINT in next_repo."""
    next_ep_prefix = f"endpoint::{next_repo}::"
    for u, v, data in kg_g.edges(data=True):
        if data.get("edge_type") == "CALLS_ENDPOINT" and str(v).startswith(next_ep_prefix):
            return u
    # Fallback: any CALLS_ENDPOINT edge
    for u, v, data in kg_g.edges(data=True):
        if data.get("edge_type") == "CALLS_ENDPOINT":
            return u
    return None
