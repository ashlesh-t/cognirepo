# pylint: disable=missing-docstring, unnecessary-lambda, import-outside-toplevel, too-few-public-methods, duplicate-code
# pylint: disable=redefined-outer-name, unused-argument, broad-exception-caught, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tests/test_graph.py — knowledge graph node/edge/traversal/serialise tests.
"""
from __future__ import annotations

import os
import pytest


class TestKnowledgeGraph:
    def test_add_and_exists(self):
        from graph.knowledge_graph import KnowledgeGraph, NodeType
        kg = KnowledgeGraph()
        kg.add_node("auth.py::verify_token", NodeType.FUNCTION, label="verify_token")
        assert kg.node_exists("auth.py::verify_token")
        assert not kg.node_exists("nonexistent::node")

    def test_add_edge_and_neighbours(self):
        from graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType
        kg = KnowledgeGraph()
        kg.add_node("auth.py::verify_token", NodeType.FUNCTION)
        kg.add_node("auth.py", NodeType.FILE)
        kg.add_edge("auth.py::verify_token", "auth.py", EdgeType.DEFINED_IN)
        neighbours = kg.get_neighbours("auth.py::verify_token", depth=1)
        node_ids = [n["node_id"] for n in neighbours]
        assert "auth.py" in node_ids

    def test_hop_distance(self):
        from graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType
        kg = KnowledgeGraph()
        kg.add_node("a", NodeType.CONCEPT)
        kg.add_node("b", NodeType.CONCEPT)
        kg.add_node("c", NodeType.CONCEPT)
        kg.add_edge("a", "b", EdgeType.RELATES_TO)
        kg.add_edge("b", "c", EdgeType.RELATES_TO)
        assert kg.hop_distance("a", "b") == 1
        assert kg.hop_distance("a", "c") == 2

    def test_hop_distance_disconnected(self):
        import sys
        from graph.knowledge_graph import KnowledgeGraph, NodeType
        kg = KnowledgeGraph()
        kg.add_node("island_a", NodeType.CONCEPT)
        kg.add_node("island_b", NodeType.CONCEPT)
        assert kg.hop_distance("island_a", "island_b") == sys.maxsize

    def test_subgraph_around(self):
        from graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType
        kg = KnowledgeGraph()
        kg.add_node("center", NodeType.FUNCTION)
        kg.add_node("left", NodeType.CONCEPT)
        kg.add_node("right", NodeType.CONCEPT)
        kg.add_edge("center", "left", EdgeType.RELATES_TO)
        kg.add_edge("center", "right", EdgeType.RELATES_TO)
        sg = kg.subgraph_around("center", radius=1)
        sg_ids = {n["node_id"] for n in sg["nodes"]}
        assert "center" in sg_ids
        assert "left" in sg_ids
        assert "right" in sg_ids

    def test_save_and_reload(self):
        from graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType
        kg = KnowledgeGraph()
        kg.add_node("persist_me", NodeType.FUNCTION, label="test_fn")
        kg.add_node("persist_file", NodeType.FILE)
        kg.add_edge("persist_me", "persist_file", EdgeType.DEFINED_IN)
        kg.save()
        assert os.path.exists(".cognirepo/graph/graph.pkl")
        # Reload in a new instance
        kg2 = KnowledgeGraph()
        assert kg2.node_exists("persist_me")
        assert kg2.node_exists("persist_file")

    def test_idempotent_add_node(self):
        from graph.knowledge_graph import KnowledgeGraph, NodeType
        kg = KnowledgeGraph()
        kg.add_node("dup", NodeType.FUNCTION, label="first")
        kg.add_node("dup", NodeType.FUNCTION, label="second")
        # Should not raise; last write wins on attrs
        assert kg.node_exists("dup")
        assert kg.G.number_of_nodes() == 1


class TestGraphUtils:
    def test_extract_entities_snake_case(self):
        from graph.graph_utils import extract_entities_from_text
        entities = extract_entities_from_text("fix bug in verify_token and decode_jwt")
        assert "verify_token" in entities
        assert "decode_jwt" in entities

    def test_extract_entities_file_extension(self):
        from graph.graph_utils import extract_entities_from_text
        entities = extract_entities_from_text("edit auth.py and update router.py")
        assert any(".py" in e for e in entities)

    def test_format_subgraph_empty(self):
        from graph.graph_utils import format_subgraph_for_context
        result = format_subgraph_for_context({"nodes": [], "edges": []})
        assert result == "(empty graph)"

    def test_format_subgraph_with_nodes(self):
        from graph.graph_utils import format_subgraph_for_context
        sg = {
            "nodes": [{"node_id": "auth.py::fn", "node_type": "FUNCTION"}],
            "edges": [{"src": "auth.py::fn", "dst": "auth.py", "edge_type": "DEFINED_IN"}],
        }
        result = format_subgraph_for_context(sg)
        assert "auth.py::fn" in result
