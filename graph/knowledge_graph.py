"""
Knowledge graph for CogniRepo — a directed NetworkX graph tracking relationships
between files, symbols, concepts, queries, and user actions.

Node types  : FILE, FUNCTION, CLASS, CONCEPT, QUERY, SESSION, USER_ACTION
Edge types  : RELATES_TO, DEFINED_IN, CALLED_BY, QUERIED_WITH, CO_OCCURS

Persistence : pickle to .cognirepo/graph/graph.pkl
              Falls back to an empty graph on load failure (version drift etc.)
"""
import os
import pickle
import sys
import warnings
from typing import Any

import networkx as nx


GRAPH_FILE = ".cognirepo/graph/graph.pkl"


class NodeType:
    FILE = "FILE"
    FUNCTION = "FUNCTION"
    CLASS = "CLASS"
    CONCEPT = "CONCEPT"
    QUERY = "QUERY"
    SESSION = "SESSION"
    USER_ACTION = "USER_ACTION"


class EdgeType:
    RELATES_TO = "RELATES_TO"
    DEFINED_IN = "DEFINED_IN"
    CALLED_BY = "CALLED_BY"
    QUERIED_WITH = "QUERIED_WITH"
    CO_OCCURS = "CO_OCCURS"


class KnowledgeGraph:
    """Thin wrapper around a networkx DiGraph with CogniRepo-specific conventions."""

    def __init__(self) -> None:
        self.G: nx.DiGraph = nx.DiGraph()
        self._load()

    # ── persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not os.path.exists(GRAPH_FILE):
            return
        try:
            with open(GRAPH_FILE, "rb") as f:
                self.G = pickle.load(f)
        except Exception as exc:  # pylint: disable=broad-except
            warnings.warn(
                f"KnowledgeGraph: could not load {GRAPH_FILE} ({exc}). "
                "Starting with an empty graph. Re-run `cognirepo index-repo` to rebuild.",
                stacklevel=2,
            )
            self.G = nx.DiGraph()

    def save(self) -> None:
        os.makedirs(os.path.dirname(GRAPH_FILE), exist_ok=True)
        with open(GRAPH_FILE, "wb") as f:
            pickle.dump(self.G, f, protocol=pickle.HIGHEST_PROTOCOL)

    # ── mutation ──────────────────────────────────────────────────────────────

    def add_node(self, node_id: str, node_type: str, **attrs: Any) -> None:
        """Idempotent add — merges attrs if node already exists."""
        if self.G.has_node(node_id):
            self.G.nodes[node_id].update(attrs)
        else:
            self.G.add_node(node_id, type=node_type, **attrs)

    def add_edge(
        self,
        src: str,
        dst: str,
        edge_type: str,
        weight: float = 1.0,
        **attrs: Any,
    ) -> None:
        """Add a directed edge; if it exists, update its weight."""
        if self.G.has_edge(src, dst):
            self.G[src][dst]["weight"] = weight
            self.G[src][dst].update(attrs)
        else:
            self.G.add_edge(src, dst, rel=edge_type, weight=weight, **attrs)

    def remove_node_edges(self, node_id: str) -> None:
        """Remove all edges incident to node_id (but keep the node)."""
        edges = list(self.G.in_edges(node_id)) + list(self.G.out_edges(node_id))
        self.G.remove_edges_from(edges)

    def nodes_for_file(self, file_path: str) -> list[str]:
        """Return all node IDs whose stored 'file' attr matches file_path."""
        return [
            n for n, d in self.G.nodes(data=True) if d.get("file") == file_path
        ]

    # ── queries ───────────────────────────────────────────────────────────────

    def node_exists(self, node_id: str) -> bool:
        return self.G.has_node(node_id)

    def get_neighbours(
        self,
        node_id: str,
        depth: int = 1,
        edge_type: str | None = None,
    ) -> list[dict]:
        """
        BFS up to `depth` hops from node_id.
        Optionally filter by edge rel type.
        Returns list of {"node_id", "type", "hops", ...node_attrs}.
        """
        if not self.G.has_node(node_id):
            return []

        visited: dict[str, int] = {node_id: 0}
        queue = [node_id]
        results: list[dict] = []

        while queue:
            current = queue.pop(0)
            current_hops = visited[current]
            if current_hops >= depth:
                continue
            for neighbor in self.G.successors(current):
                if neighbor in visited:
                    continue
                edge_data = self.G[current][neighbor]
                if edge_type and edge_data.get("rel") != edge_type:
                    continue
                hops = current_hops + 1
                visited[neighbor] = hops
                node_data = dict(self.G.nodes[neighbor])
                node_data["node_id"] = neighbor
                node_data["hops"] = hops
                results.append(node_data)
                queue.append(neighbor)

        return results

    def hop_distance(self, src: str, dst: str) -> int:
        """Shortest hop distance; sys.maxsize if no path or either node missing."""
        if not self.G.has_node(src) or not self.G.has_node(dst):
            return sys.maxsize
        try:
            return nx.shortest_path_length(self.G, src, dst)
        except nx.NetworkXNoPath:
            return sys.maxsize

    def shortest_path(self, src: str, dst: str) -> list[str] | None:
        """Returns node list of shortest path, or None if no path."""
        try:
            return nx.shortest_path(self.G, src, dst)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def subgraph_around(self, node_id: str, radius: int = 2) -> dict:
        """
        Returns {"nodes": [...], "edges": [...]} of the ego graph around node_id.
        Suitable for context injection (pass to format_subgraph_for_context).
        """
        if not self.G.has_node(node_id):
            return {"nodes": [], "edges": []}

        ego = nx.ego_graph(self.G, node_id, radius=radius, undirected=True)

        nodes = []
        for n, d in ego.nodes(data=True):
            entry = dict(d)
            entry["node_id"] = n
            nodes.append(entry)

        edges = []
        for u, v, d in ego.edges(data=True):
            edges.append({"src": u, "dst": v, "rel": d.get("rel", "?"), "weight": d.get("weight", 1.0)})

        return {"nodes": nodes, "edges": edges}

    # ── stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "nodes": self.G.number_of_nodes(),
            "edges": self.G.number_of_edges(),
        }
