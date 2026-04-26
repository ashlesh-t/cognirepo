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

EdgeKind = Literal["IMPORTS", "CALLS_API", "SHARES_SCHEMA", "CHILD_OF", "DISCOVERED"]
_VALID_EDGE_KINDS: frozenset[str] = frozenset({"IMPORTS", "CALLS_API", "SHARES_SCHEMA", "CHILD_OF", "DISCOVERED"})
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
            self._migrate_from_orgs_json()
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

    def _migrate_from_orgs_json(self) -> None:
        """One-time migration: read orgs.json repo lists into the org graph."""
        try:
            orgs_path = os.path.join(os.path.expanduser("~"), ".cognirepo", "orgs.json")
            if not os.path.exists(orgs_path):
                return
            import json  # pylint: disable=import-outside-toplevel
            with open(orgs_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            migrated = 0
            for org_data in data.values():
                if not isinstance(org_data, dict):
                    continue
                for repo in org_data.get("repos", []):
                    if os.path.isdir(repo):
                        self.add_repo(repo)
                        migrated += 1
                for proj in org_data.get("projects", {}).values():
                    repos = proj.get("repos", [])
                    for i, repo in enumerate(repos):
                        if os.path.isdir(repo):
                            parent = repos[0] if i > 0 else None
                            self.add_repo(repo, parent_path=parent)
                            migrated += 1
            if migrated:
                logger.info("OrgGraph: migrated %d repos from orgs.json", migrated)
                self.save()
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("OrgGraph: orgs.json migration skipped: %s", exc)

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

    def add_repo(
        self,
        path: str,
        parent_path: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """
        Register a repo node. If parent_path is given, adds a CHILD_OF edge
        so get_children(parent_path) returns this repo.
        """
        abs_path = os.path.abspath(path)
        node_attrs = {"node_type": "REPO", "name": os.path.basename(abs_path)}
        if parent_path:
            node_attrs["parent"] = os.path.abspath(parent_path)
        if metadata:
            node_attrs.update(metadata)
        self.G.add_node(abs_path, **node_attrs)
        if parent_path:
            abs_parent = os.path.abspath(parent_path)
            # Ensure parent node exists
            if not self.G.has_node(abs_parent):
                self.G.add_node(abs_parent, node_type="REPO", name=os.path.basename(abs_parent))
            self.G.add_edge(abs_path, abs_parent, kind="CHILD_OF", direction="forward", auto=False)
            self.G.add_edge(abs_parent, abs_path, kind="CHILD_OF", direction="reverse", auto=False)

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

    def link_repos(
        self,
        src: str,
        dst: str,
        kind: str = "IMPORTS",
        note: str = "",
        bidirectional: bool = True,
        auto: bool = False,
    ) -> None:
        """
        Record an inter-repo dependency edge. kind must be one of:
        IMPORTS, CALLS_API, SHARES_SCHEMA, DISCOVERED.
        Prefer this over link() for agent-driven edge creation.
        """
        edge_kind = kind if kind in _VALID_EDGE_KINDS else "DISCOVERED"
        self.link(src, dst, kind=edge_kind, bidirectional=bidirectional, auto=auto)  # type: ignore[arg-type]
        if note:
            abs_src = os.path.abspath(src)
            abs_dst = os.path.abspath(dst)
            if self.G.has_edge(abs_src, abs_dst):
                self.G[abs_src][abs_dst]["note"] = note

    def get_children(self, repo_path: str) -> list[str]:
        """Return direct children (repos linked with CHILD_OF, forward direction)."""
        abs_path = os.path.abspath(repo_path)
        if not self.G.has_node(abs_path):
            return []
        return [
            n for n in self.G.successors(abs_path)
            if self.G[abs_path][n].get("kind") == "CHILD_OF"
            and self.G[abs_path][n].get("direction") == "reverse"
        ]

    def get_siblings(self, repo_path: str) -> list[str]:
        """Return repos that share the same parent as repo_path."""
        abs_path = os.path.abspath(repo_path)
        node_data = self.G.nodes.get(abs_path, {})
        parent = node_data.get("parent")
        if not parent:
            return []
        return [c for c in self.get_children(parent) if c != abs_path]

    def root_repos(self) -> list[str]:
        """Return repos with no parent (org roots)."""
        return [
            n for n, d in self.G.nodes(data=True)
            if d.get("node_type") == "REPO" and not d.get("parent")
        ]

    def infer_import_edges(self, repo_path: str, ast_index: dict) -> int:
        """
        Scan ast_index for import statements. If an imported package name matches
        a known sibling repo name, add an IMPORTS edge. Returns count of edges added.
        """
        abs_path = os.path.abspath(repo_path)
        known_repos = {os.path.basename(r): r for r in self.list_repos() if r != abs_path}
        if not known_repos:
            return 0
        added = 0
        for _file, file_data in ast_index.get("files", {}).items():
            for sym in file_data.get("symbols", []):
                if sym.get("type") not in ("IMPORT", "FROM_IMPORT"):
                    continue
                imported = sym.get("name", "").split(".")[0].replace("-", "_")
                if imported in known_repos:
                    target = known_repos[imported]
                    if not self.G.has_edge(abs_path, target):
                        self.link(abs_path, target, kind="IMPORTS", bidirectional=False, auto=True)
                        added += 1
        return added

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
