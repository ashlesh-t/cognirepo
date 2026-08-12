# pylint: disable=missing-docstring, unnecessary-lambda, import-outside-toplevel, too-few-public-methods, duplicate-code
# pylint: disable=redefined-outer-name, unused-argument, broad-exception-caught, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_similarity_edges.py — COGNIREPO-202 acceptance criteria.

Uses the session-scoped mock_embeddings fixture (tests/conftest.py): each embed text gets
a one-hot vector keyed on the FIRST matching keyword from a fixed list ("jwt", "docker", …).
Two symbols whose embed text both hit the same keyword get IDENTICAL vectors (cosine 1.0,
well above the 0.80 threshold); symbols hitting different keywords are orthogonal (cosine 0.0).
This makes near-duplicate vs. unrelated deterministic without a real embedding model.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest


@pytest.fixture()
def fresh_indexer(isolated_cognirepo):
    from data.graph.knowledge_graph import KnowledgeGraph
    from intelligence.indexer.ast_indexer import ASTIndexer
    from intelligence.indexer.language_registry import clear_cache
    clear_cache()
    kg = KnowledgeGraph()
    return ASTIndexer(graph=kg)


def _write(tmp: Path, name: str, content: str) -> Path:
    p = tmp / name
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def _similar_to_edges(graph):
    from data.graph.knowledge_graph import EdgeType
    return [
        (u, v) for u, v, d in graph.G.edges(data=True)
        if d.get("rel") == EdgeType.SIMILAR_TO
    ]


class TestSimilarityEdgeCreation:
    def test_near_duplicate_functions_get_similar_to_edge(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "a.py", '''\
            def verify_a():
                """jwt token check"""
                pass
        ''')
        _write(tmp_path, "b.py", '''\
            def verify_b():
                """jwt token check"""
                pass
        ''')

        fresh_indexer.index_repo(str(tmp_path))
        edges = _similar_to_edges(fresh_indexer.graph)

        assert ("a.py::verify_a", "b.py::verify_b") in edges
        assert ("b.py::verify_b", "a.py::verify_a") in edges  # both directions

        # weight is the cosine similarity, recorded ≥ the 0.80 threshold
        w = fresh_indexer.graph.G["a.py::verify_a"]["b.py::verify_b"]["weight"]
        assert w >= 0.80

    def test_subgraph_shows_counterpart_from_either_side(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "a.py", '''\
            def verify_a():
                """jwt token check"""
                pass
        ''')
        _write(tmp_path, "b.py", '''\
            def verify_b():
                """jwt token check"""
                pass
        ''')
        fresh_indexer.index_repo(str(tmp_path))

        sub_a = fresh_indexer.graph.subgraph_around("a.py::verify_a", radius=1)
        sub_b = fresh_indexer.graph.subgraph_around("b.py::verify_b", radius=1)
        assert "b.py::verify_b" in {n["node_id"] for n in sub_a["nodes"]}
        assert "a.py::verify_a" in {n["node_id"] for n in sub_b["nodes"]}

    def test_unrelated_symbols_get_no_edge(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "a.py", '''\
            def verify_a():
                """jwt token check"""
                pass
        ''')
        _write(tmp_path, "b.py", '''\
            def build_image():
                """docker build helper"""
                pass
        ''')

        fresh_indexer.index_repo(str(tmp_path))
        edges = _similar_to_edges(fresh_indexer.graph)
        assert edges == []

    def test_same_file_pair_never_gets_edge(self, fresh_indexer, tmp_path, monkeypatch):
        """DEFINED_IN already relates same-file symbols — SIMILAR_TO would be redundant."""
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "a.py", '''\
            def verify_a():
                """jwt token check"""
                pass

            def verify_a2():
                """jwt token check"""
                pass
        ''')

        fresh_indexer.index_repo(str(tmp_path))
        edges = _similar_to_edges(fresh_indexer.graph)
        assert edges == []

    def test_cap_enforced_at_five_per_node(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        hub_file = _write(tmp_path, "hub.py", '''\
            def verify_hub():
                """jwt token check"""
                pass
        ''')
        for i in range(8):
            _write(tmp_path, f"dup{i}.py", f'''\
                def verify_{i}():
                    """jwt token check"""
                    pass
            ''')

        fresh_indexer.index_repo(str(tmp_path))
        out_degree = sum(
            1 for _, _, d in fresh_indexer.graph.G.out_edges("hub.py::verify_hub", data=True)
            if d.get("rel") == "SIMILAR_TO"
        )
        assert out_degree <= 5


class TestSimilarityEdgeGate:
    def test_gate_off_yields_zero_edges(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cognirepo_dir = tmp_path / ".cognirepo"
        cognirepo_dir.mkdir(exist_ok=True)
        (cognirepo_dir / "config.json").write_text(
            json.dumps({"indexing": {"similarity_edges": False}}), encoding="utf-8"
        )
        _write(tmp_path, "a.py", '''\
            def verify_a():
                """jwt token check"""
                pass
        ''')
        _write(tmp_path, "b.py", '''\
            def verify_b():
                """jwt token check"""
                pass
        ''')

        fresh_indexer.index_repo(str(tmp_path))
        assert _similar_to_edges(fresh_indexer.graph) == []

    def test_gate_off_graph_still_loads_fine(self, fresh_indexer, tmp_path, monkeypatch):
        """Existing graphs load fine either way — unknown rel values are already tolerated."""
        monkeypatch.chdir(tmp_path)
        cognirepo_dir = tmp_path / ".cognirepo"
        cognirepo_dir.mkdir(exist_ok=True)
        (cognirepo_dir / "config.json").write_text(
            json.dumps({"indexing": {"similarity_edges": False}}), encoding="utf-8"
        )
        _write(tmp_path, "a.py", "def foo(): pass\n")

        summary = fresh_indexer.index_repo(str(tmp_path))
        assert summary["similarity_edges"] == 0

        fresh_indexer.graph.save()
        from data.graph.knowledge_graph import KnowledgeGraph
        reloaded = KnowledgeGraph()
        assert reloaded.G.number_of_nodes() > 0
