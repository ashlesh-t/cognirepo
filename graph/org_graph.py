# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
graph/org_graph.py — Bidirectional inter-repo dependency graph.

Stores a global NetworkX DiGraph linking repos within an organization.
Each repo is a node; edges represent dependency relationships.

Persisted at: ~/.cognirepo/org_graph.pkl

Edge types:
  IMPORTS    — A's manifest (pyproject.toml, package.json, go.mod, etc.)
               lists B as a dependency
  CALLS_API  — A contains HTTP client calls to B's known service URL patterns
  SHARES_SCHEMA — A and B both import from the same shared models/proto repo

Both directions are stored explicitly (A→B and B→A with direction attr)
so get_dependents() is O(degree) rather than requiring a full graph reversal.
"""
from __future__ import annotations

import logging
import os
import pickle
from typing import Literal

import networkx as nx

logger = logging.getLogger(__name__)


def _org_lock():
    """Cross-process file lock for org_graph.pkl — scoped to ~/.cognirepo/."""
    try:
        from filelock import FileLock  # pylint: disable=import-outside-toplevel
        lock_path = os.path.join(os.path.expanduser("~"), ".cognirepo", "org_graph.lock")
        return FileLock(lock_path)
    except ImportError as exc:
        raise ImportError(
            "filelock is required for concurrent write safety. "
            "Run: pip install filelock"
        ) from exc

EdgeKind = Literal["IMPORTS", "CALLS_API", "SHARES_SCHEMA"]
_ORG_GRAPH_FILE = os.path.join(os.path.expanduser("~"), ".cognirepo", "org_graph.pkl")


def _graph_path() -> str:
    return os.environ.get("COGNIREPO_ORG_GRAPH", _ORG_GRAPH_FILE)


class OrgGraph:
    """
    Bidirectional inter-repo dependency graph for an organization.

    Nodes: absolute repo paths (str)
    Edges: (src, dst, {"kind": EdgeKind, "direction": "forward"|"reverse", "auto": bool})
    """

    def __init__(self) -> None:
        self.G: nx.DiGraph = nx.DiGraph()
        self._load()

    # ── persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        path = _graph_path()
        if not os.path.exists(path):
            return
        try:
            with _org_lock():
                with open(path, "rb") as f:
                    raw = f.read()
            from security import get_storage_config  # pylint: disable=import-outside-toplevel
            encrypt, project_id = get_storage_config()
            if encrypt and project_id:
                from security.encryption import get_or_create_key, decrypt_bytes  # pylint: disable=import-outside-toplevel
                raw = decrypt_bytes(raw, get_or_create_key(project_id))
            self.G = pickle.loads(raw)  # nosec B301
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("OrgGraph: failed to load %s: %s", path, exc)
            self.G = nx.DiGraph()

    def save(self) -> None:
        path = _graph_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            from security import get_storage_config  # pylint: disable=import-outside-toplevel
            encrypt, project_id = get_storage_config()
            raw = pickle.dumps(self.G, protocol=pickle.HIGHEST_PROTOCOL)
            if encrypt and project_id:
                from security.encryption import get_or_create_key, encrypt_bytes  # pylint: disable=import-outside-toplevel
                raw = encrypt_bytes(raw, get_or_create_key(project_id))
            with _org_lock():
                with open(path, "wb") as f:
                    f.write(raw)
        except OSError as exc:
            logger.error("OrgGraph: failed to save: %s", exc)

    # ── node management ───────────────────────────────────────────────────────

    def add_repo(self, path: str, metadata: dict | None = None) -> None:
        abs_path = os.path.abspath(path)
        self.G.add_node(abs_path, **(metadata or {}), node_type="REPO")

    def remove_repo(self, path: str) -> None:
        abs_path = os.path.abspath(path)
        if self.G.has_node(abs_path):
            self.G.remove_node(abs_path)

    def list_repos(self) -> list[str]:
        return [n for n, d in self.G.nodes(data=True) if d.get("node_type") == "REPO"]

    # ── edge management ───────────────────────────────────────────────────────

    def link(
        self,
        src: str,
        dst: str,
        kind: EdgeKind = "IMPORTS",
        bidirectional: bool = True,
        auto: bool = False,
    ) -> None:
        """
        Add a dependency edge src → dst.
        If bidirectional=True, also stores the reverse edge dst → src
        with direction="reverse" so get_dependents() is O(degree).
        """
        abs_src = os.path.abspath(src)
        abs_dst = os.path.abspath(dst)
        if abs_src == abs_dst:
            return
        self.add_repo(abs_src)
        self.add_repo(abs_dst)
        self.G.add_edge(abs_src, abs_dst, kind=kind, direction="forward", auto=auto)
        if bidirectional:
            self.G.add_edge(abs_dst, abs_src, kind=kind, direction="reverse", auto=auto)

    def unlink(self, src: str, dst: str, kind: EdgeKind | None = None) -> None:
        abs_src = os.path.abspath(src)
        abs_dst = os.path.abspath(dst)
        for u, v in [(abs_src, abs_dst), (abs_dst, abs_src)]:
            if self.G.has_edge(u, v):
                if kind is None or self.G[u][v].get("kind") == kind:
                    self.G.remove_edge(u, v)

    # ── traversal ─────────────────────────────────────────────────────────────

    def get_dependencies(self, repo: str, depth: int = 2) -> list[dict]:
        """
        Return repos that `repo` depends on (forward edges), up to `depth` hops.
        Result includes edge type and hop distance.
        """
        abs_repo = os.path.abspath(repo)
        return self._bfs(abs_repo, direction="forward", max_depth=depth)

    def get_dependents(self, repo: str, depth: int = 2) -> list[dict]:
        """
        Return repos that depend ON `repo` (reverse edges), up to `depth` hops.
        """
        abs_repo = os.path.abspath(repo)
        return self._bfs(abs_repo, direction="reverse", max_depth=depth)

    def _bfs(self, start: str, direction: str, max_depth: int) -> list[dict]:
        if not self.G.has_node(start):
            return []
        visited: set[str] = {start}
        queue: list[tuple[str, int]] = [(start, 0)]
        results: list[dict] = []
        while queue:
            node, dist = queue.pop(0)
            if dist >= max_depth:
                continue
            for neighbor in self.G.successors(node):
                edge_data = self.G[node][neighbor]
                if edge_data.get("direction") != direction:
                    continue
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                results.append({
                    "repo": neighbor,
                    "name": os.path.basename(neighbor),
                    "kind": edge_data.get("kind", "IMPORTS"),
                    "depth": dist + 1,
                    "auto": edge_data.get("auto", False),
                })
                queue.append((neighbor, dist + 1))
        return results

    def shortest_path(self, src: str, dst: str) -> list[str]:
        abs_src = os.path.abspath(src)
        abs_dst = os.path.abspath(dst)
        try:
            path = nx.shortest_path(self.G, abs_src, abs_dst)
            return path
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    # ── serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize graph to a JSON-safe dict for MCP responses."""
        nodes = [
            {"repo": n, "name": os.path.basename(n), **d}
            for n, d in self.G.nodes(data=True)
        ]
        edges = [
            {
                "src": u,
                "dst": v,
                "src_name": os.path.basename(u),
                "dst_name": os.path.basename(v),
                **d,
            }
            for u, v, d in self.G.edges(data=True)
            if d.get("direction") == "forward"
        ]
        return {"nodes": nodes, "edges": edges, "repo_count": len(nodes)}

    def summary(self) -> dict:
        repos = self.list_repos()
        forward_edges = [
            (u, v, d) for u, v, d in self.G.edges(data=True)
            if d.get("direction") == "forward"
        ]
        return {
            "repo_count": len(repos),
            "edge_count": len(forward_edges),
            "repos": [os.path.basename(r) for r in repos],
        }


# ── module-level singleton (lazy) ─────────────────────────────────────────────

_ORG_GRAPH: OrgGraph | None = None


def get_org_graph() -> OrgGraph:
    global _ORG_GRAPH  # pylint: disable=global-statement
    if _ORG_GRAPH is None:
        _ORG_GRAPH = OrgGraph()
    return _ORG_GRAPH


def invalidate_org_graph() -> None:
    global _ORG_GRAPH  # pylint: disable=global-statement
    _ORG_GRAPH = None
