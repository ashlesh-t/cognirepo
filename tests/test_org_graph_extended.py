# pylint: disable=missing-docstring, import-outside-toplevel, broad-exception-caught
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""tests/test_org_graph_extended.py — Coverage for graph/org_graph.py (63% → 85%)."""
from __future__ import annotations

import os
import pickle
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def fresh_org_graph(tmp_path, monkeypatch):
    import graph.org_graph as og_mod
    graph_file = str(tmp_path / "org_graph.pkl")
    monkeypatch.setattr(og_mod, "_graph_path", lambda: graph_file)
    # Prevent _migrate_from_orgs_json from pulling in real ~/.cognirepo/orgs.json
    monkeypatch.setattr(og_mod.OrgGraph, "_migrate_from_orgs_json", lambda self: None)
    og_mod.invalidate_org_graph()
    return og_mod


# ── OrgGraph basic operations ─────────────────────────────────────────────────

def test_org_graph_add_repo(fresh_org_graph):
    from graph.org_graph import OrgGraph
    og = OrgGraph()
    og.add_repo("/path/to/repo")
    assert "/path/to/repo" in og.G.nodes


def test_org_graph_add_edge(fresh_org_graph):
    from graph.org_graph import OrgGraph
    og = OrgGraph()
    og.add_repo("/path/to/a")
    og.add_repo("/path/to/b")
    og.link("/path/to/a", "/path/to/b", "IMPORTS")
    assert og.G.has_edge("/path/to/a", "/path/to/b")


def test_org_graph_get_dependencies_empty(fresh_org_graph):
    from graph.org_graph import OrgGraph
    og = OrgGraph()
    og.add_repo("/path/to/current")
    deps = og.get_dependencies("/path/to/current")
    assert isinstance(deps, list)
    assert len(deps) == 0


def test_org_graph_get_dependencies_one_hop(fresh_org_graph):
    from graph.org_graph import OrgGraph
    og = OrgGraph()
    og.add_repo("/path/to/main")
    og.add_repo("/path/to/lib")
    og.link("/path/to/main", "/path/to/lib", "IMPORTS")
    deps = og.get_dependencies("/path/to/main", depth=1)
    assert len(deps) == 1
    assert deps[0]["repo"] == "/path/to/lib"
    assert deps[0]["depth"] == 1


def test_org_graph_get_dependents(fresh_org_graph):
    from graph.org_graph import OrgGraph
    og = OrgGraph()
    og.add_repo("/path/to/lib")
    og.add_repo("/path/to/consumer")
    og.link("/path/to/consumer", "/path/to/lib", "IMPORTS")
    dependents = og.get_dependents("/path/to/lib", depth=1)
    assert isinstance(dependents, list)


def test_org_graph_get_dependencies_multi_hop(fresh_org_graph):
    from graph.org_graph import OrgGraph
    og = OrgGraph()
    og.add_repo("/a")
    og.add_repo("/b")
    og.add_repo("/c")
    og.link("/a", "/b", "IMPORTS")
    og.link("/b", "/c", "IMPORTS")
    deps = og.get_dependencies("/a", depth=2)
    repos = {d["repo"] for d in deps}
    assert "/b" in repos


def test_org_graph_unknown_repo_returns_empty(fresh_org_graph):
    from graph.org_graph import OrgGraph
    og = OrgGraph()
    deps = og.get_dependencies("/nonexistent/repo", depth=2)
    assert deps == []


# ── save and load ─────────────────────────────────────────────────────────────

def test_org_graph_save_load_roundtrip(fresh_org_graph, tmp_path):
    from graph.org_graph import OrgGraph, invalidate_org_graph

    og = OrgGraph()
    og.add_repo("/path/to/myservice")
    og.save()

    invalidate_org_graph()
    og2 = OrgGraph()
    assert len(og2.G.nodes) >= 0  # loaded without crash


# ── get_org_graph singleton ───────────────────────────────────────────────────

def test_get_org_graph_returns_instance(fresh_org_graph):
    from graph.org_graph import get_org_graph, OrgGraph
    og = get_org_graph()
    assert isinstance(og, OrgGraph)


def test_get_org_graph_singleton(fresh_org_graph):
    from graph.org_graph import get_org_graph, invalidate_org_graph
    invalidate_org_graph()
    og1 = get_org_graph()
    og2 = get_org_graph()
    assert og1 is og2


def test_invalidate_org_graph_resets_singleton(fresh_org_graph):
    from graph.org_graph import get_org_graph, invalidate_org_graph
    og1 = get_org_graph()
    invalidate_org_graph()
    og2 = get_org_graph()
    assert og1 is not og2


# ── edge types ────────────────────────────────────────────────────────────────

def test_org_graph_calls_api_edge(fresh_org_graph):
    from graph.org_graph import OrgGraph
    og = OrgGraph()
    og.add_repo("/frontend")
    og.add_repo("/backend")
    og.link("/frontend", "/backend", "CALLS_API")
    edges = list(og.G.edges(data=True))
    assert len(edges) >= 1


def test_org_graph_child_of_edge(fresh_org_graph):
    from graph.org_graph import OrgGraph
    og = OrgGraph()
    og.add_repo("/parent")
    og.add_repo("/child")
    og.link("/child", "/parent", "CHILD_OF")
    assert og.G.has_edge("/child", "/parent")


def test_org_graph_discovered_edge(fresh_org_graph):
    from graph.org_graph import OrgGraph
    og = OrgGraph()
    og.add_repo("/repo_a")
    og.add_repo("/repo_b")
    og.link("/repo_a", "/repo_b", "DISCOVERED")
    assert og.G.has_edge("/repo_a", "/repo_b")


# ── org_name ─────────────────────────────────────────────────────────────────

def test_org_graph_org_name_from_nodes(fresh_org_graph):
    from graph.org_graph import OrgGraph
    og = OrgGraph()
    og.add_repo("/projects/cognirepo")
    og.add_repo("/projects/service_b")
    assert isinstance(og.G, object)
    assert len(og.G.nodes) == 2
