# Copyright (c) 2026 Ashlesh T. — AGPL-3.0 (see LICENSE)
"""KnowledgeGraph read facade (#115, ADR 002): same answers as `.G`, and nobody reaches around it."""
from __future__ import annotations

import ast
import pathlib

import pytest

from data.graph.knowledge_graph import EdgeType, KnowledgeGraph, NodeType

_REPO = pathlib.Path(__file__).resolve().parent.parent
_ROOTS = ("core", "data", "intelligence", "interface", "ops")
#: files that own a networkx graph and may touch `.G` directly
_OWNERS = {"data/graph/knowledge_graph.py", "data/graph/org_graph.py",
           "data/graph/sqlite_graph.py", "data/graph/sqlite_import.py",
           "data/graph/migrate.py"}   # the SQLite backend never has a .G; the importer reads a pickle
#: variable names that hold the *org* graph (a different class with its own `.G`)
_ORG_NAMES = {"og", "_og", "_og3", "org", "org_graph", "graph_org"}


@pytest.fixture
def kg(isolated_cognirepo):
    g = KnowledgeGraph()
    g.add_node("file::a.py", NodeType.FILE)
    g.add_node("a.py::f", NodeType.FUNCTION, file="a.py", line=3)
    g.add_node("a.py::g", NodeType.FUNCTION, file="a.py", line=9)
    g.add_edge("a.py::f", "a.py::g", EdgeType.CALLS)
    g.add_edge("file::a.py", "a.py::f", EdgeType.DEFINED_IN)
    return g


class TestFacadeMatchesNetworkx:
    def test_counts(self, kg):
        assert (kg.node_count(), kg.edge_count()) == (kg.G.number_of_nodes(), kg.G.number_of_edges()) == (3, 2)

    def test_membership_and_adjacency(self, kg):
        assert kg.has_edge("a.py::f", "a.py::g") and not kg.has_edge("a.py::g", "a.py::f")
        assert kg.successors("a.py::f") == ["a.py::g"]
        assert kg.predecessors("a.py::g") == ["a.py::f"]
        assert sorted(kg.node_ids()) == sorted(kg.G.nodes())

    def test_attrs_and_edge_data(self, kg):
        assert kg.node_attrs("a.py::f")["line"] == 3
        assert kg.edge_data("a.py::f", "a.py::g")["rel"] == EdgeType.CALLS
        assert kg.edge_data("a.py::g", "a.py::f") is None
        assert dict(kg.nodes_with_data())["a.py::g"]["line"] == 9
        assert {(u, v) for u, v, _ in kg.edges_with_data()} == {("a.py::f", "a.py::g"), ("file::a.py", "a.py::f")}

    def test_degrees(self, kg):
        assert kg.degree("a.py::f") == kg.G.degree("a.py::f") == 2
        assert dict(kg.in_degrees())["a.py::g"] == 1

    def test_missing_nodes_are_empty_not_errors(self, kg):
        assert kg.successors("nope") == [] and kg.predecessors("nope") == []
        assert kg.node_attrs("nope") == {} and kg.degree("nope") == 0 and kg.edge_data("nope", "x") is None

    def test_results_are_copies_not_live_views(self, kg):
        kg.node_attrs("a.py::f")["line"] = 999
        kg.edge_data("a.py::f", "a.py::g")["rel"] = "X"
        nodes = kg.node_ids()
        kg.add_node("late", NodeType.FILE)       # mutating while holding a snapshot must be safe
        assert "late" not in nodes
        assert kg.node_attrs("a.py::f")["line"] == 3
        assert kg.edge_data("a.py::f", "a.py::g")["rel"] == EdgeType.CALLS

    def test_paths_and_undirected_view(self, kg):
        assert kg.path_between("file::a.py", "a.py::g") == ["file::a.py", "a.py::f", "a.py::g"]
        assert kg.path_between("a.py::g", "file::a.py") is None
        assert kg.path_between("a.py::g", "file::a.py", undirected=True) is not None
        assert kg.path_between("zzz", "a.py::g") is None
        view = kg.undirected_snapshot()
        assert view.hops("a.py::g", "file::a.py") == 2
        assert view.hops("a.py::g", "zzz") is None


def _offenders() -> list[str]:
    out = []
    for root in _ROOTS:
        for path in (_REPO / root).rglob("*.py"):
            rel = path.relative_to(_REPO).as_posix()
            if rel in _OWNERS:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Attribute) and node.attr == "G":
                    base = node.value
                    name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", None)
                    if name not in _ORG_NAMES:
                        out.append(f"{rel}:{node.lineno} {ast.unparse(node)}")
    return out


def test_nothing_outside_the_graph_modules_reaches_into_dot_G():
    """ADR 002: `.G` is private to KnowledgeGraph so the store behind it can change. Use the facade
    (node_count, successors, node_attrs, edge_data, ...) or add a method to it."""
    assert _offenders() == []
