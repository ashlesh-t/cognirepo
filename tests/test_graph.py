# pylint: disable=missing-docstring, unnecessary-lambda, import-outside-toplevel, too-few-public-methods, duplicate-code
# pylint: disable=redefined-outer-name, unused-argument, broad-exception-caught, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_graph.py — knowledge graph node/edge/traversal/serialise tests.
"""
from __future__ import annotations

import os


class TestKnowledgeGraph:
    def test_add_and_exists(self):
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType
        kg = KnowledgeGraph()
        kg.add_node("auth.py::verify_token", NodeType.FUNCTION, label="verify_token")
        assert kg.node_exists("auth.py::verify_token")
        assert not kg.node_exists("nonexistent::node")

    def test_add_edge_and_neighbours(self):
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType
        kg = KnowledgeGraph()
        kg.add_node("auth.py::verify_token", NodeType.FUNCTION)
        kg.add_node("auth.py", NodeType.FILE)
        kg.add_edge("auth.py::verify_token", "auth.py", EdgeType.DEFINED_IN)
        neighbours = kg.get_neighbours("auth.py::verify_token", depth=1)
        node_ids = [n["node_id"] for n in neighbours]
        assert "auth.py" in node_ids

    def test_hop_distance(self):
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType
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
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType
        kg = KnowledgeGraph()
        kg.add_node("island_a", NodeType.CONCEPT)
        kg.add_node("island_b", NodeType.CONCEPT)
        assert kg.hop_distance("island_a", "island_b") == sys.maxsize

    def test_subgraph_around(self):
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType
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
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType
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
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType
        kg = KnowledgeGraph()
        kg.add_node("dup", NodeType.FUNCTION, label="first")
        kg.add_node("dup", NodeType.FUNCTION, label="second")
        # Should not raise; last write wins on attrs
        assert kg.node_exists("dup")
        assert kg.G.number_of_nodes() == 1


class TestKnowledgeGraphIntegrity:
    """COGNIREPO-201: integrity sweep — orphans + dangling file nodes."""

    def test_clean_graph_reports_zero(self, tmp_path):
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType
        kg = KnowledgeGraph()
        (tmp_path / "auth.py").write_text("def verify_token(): pass\n", encoding="utf-8")
        kg.add_node("auth.py", NodeType.FILE)
        kg.add_node("auth.py::verify_token", NodeType.FUNCTION, file="auth.py")
        kg.add_edge("auth.py::verify_token", "auth.py", EdgeType.DEFINED_IN)
        report = kg.integrity_report(str(tmp_path))
        assert report["orphans"] == []
        assert report["dangling_files"] == []
        assert report["swept_at"]

    def test_orphan_restricted_to_file_function_class(self, tmp_path):
        """MEMORY/SESSION/ERROR/QUERY/CONCEPT nodes are legitimately edge-free early on."""
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType
        kg = KnowledgeGraph()
        kg.add_node("orphan_fn", NodeType.FUNCTION, file="ghost.py")
        kg.add_node("m1", NodeType.MEMORY)
        kg.add_node("s1", NodeType.SESSION)
        kg.add_node("e1", NodeType.ERROR)
        kg.add_node("concept1", NodeType.CONCEPT)
        report = kg.integrity_report(str(tmp_path))
        assert report["orphans"] == ["orphan_fn"]

    def test_dangling_file_detected_and_deduped(self, tmp_path):
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType
        kg = KnowledgeGraph()
        kg.add_node("gone.py", NodeType.FILE)
        kg.add_node("gone.py::fn_a", NodeType.FUNCTION, file="gone.py")
        kg.add_node("gone.py::fn_b", NodeType.FUNCTION, file="gone.py")
        kg.add_edge("gone.py::fn_a", "gone.py", EdgeType.DEFINED_IN)
        kg.add_edge("gone.py::fn_b", "gone.py", EdgeType.DEFINED_IN)
        report = kg.integrity_report(str(tmp_path))
        # gone.py never existed under tmp_path — one dangling entry, not three.
        assert report["dangling_files"] == ["gone.py"]

    def test_repair_apply_removes_dangling_only(self, tmp_path):
        """AC3: --apply removes danglers only; orphan CONCEPTs untouched."""
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType
        kg = KnowledgeGraph()
        (tmp_path / "live.py").write_text("def keep(): pass\n", encoding="utf-8")
        kg.add_node("live.py", NodeType.FILE)
        kg.add_node("live.py::keep", NodeType.FUNCTION, file="live.py")
        kg.add_edge("live.py::keep", "live.py", EdgeType.DEFINED_IN)

        kg.add_node("gone.py", NodeType.FILE)
        kg.add_node("gone.py::stale", NodeType.FUNCTION, file="gone.py")
        kg.add_edge("gone.py::stale", "gone.py", EdgeType.DEFINED_IN)

        kg.add_node("orphan_concept", NodeType.CONCEPT, unresolved=True)

        report = kg.integrity_report(str(tmp_path))
        for f in report["dangling_files"]:
            kg.remove_file_nodes(f)

        assert kg.node_exists("live.py") and kg.node_exists("live.py::keep")
        assert not kg.node_exists("gone.py") and not kg.node_exists("gone.py::stale")
        assert kg.node_exists("orphan_concept")  # untouched — no 'file' attr

        report2 = kg.integrity_report(str(tmp_path))
        assert report2["dangling_files"] == []


class TestKnowledgeGraphCorruptionQuarantine:
    """COGNIREPO-103 AC2: a corrupt graph.pkl is quarantined, not silently overwritten."""

    def test_corrupt_pickle_is_quarantined_on_load(self, tmp_path):
        import glob
        from data.graph.knowledge_graph import KnowledgeGraph, _graph_file

        path = _graph_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"not a valid pickle stream")

        kg = KnowledgeGraph()  # must not raise

        assert kg.G.number_of_nodes() == 0  # started fresh
        assert not os.path.exists(path)  # original corrupt file moved, not left in place
        quarantined = glob.glob(path + ".corrupt-*")
        assert len(quarantined) == 1

    def test_server_starts_and_quarantine_warning_names_the_file(self, tmp_path):
        import glob
        import warnings
        from data.graph.knowledge_graph import KnowledgeGraph, _graph_file

        path = _graph_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"garbage")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            KnowledgeGraph()

        quarantined = glob.glob(path + ".corrupt-*")
        assert len(quarantined) == 1
        msgs = [str(w.message) for w in caught]
        assert any(os.path.basename(quarantined[0]) in m for m in msgs)


class TestGraphUtils:
    def test_extract_entities_snake_case(self):
        from data.graph.graph_utils import extract_entities_from_text
        entities = extract_entities_from_text("fix bug in verify_token and decode_jwt")
        assert "verify_token" in entities
        assert "decode_jwt" in entities

    def test_extract_entities_file_extension(self):
        from data.graph.graph_utils import extract_entities_from_text
        entities = extract_entities_from_text("edit auth.py and update router.py")
        assert any(".py" in e for e in entities)

    def test_format_subgraph_empty(self):
        from data.graph.graph_utils import format_subgraph_for_context
        result = format_subgraph_for_context({"nodes": [], "edges": []})
        assert result == "(empty graph)"

    def test_format_subgraph_with_nodes(self):
        from data.graph.graph_utils import format_subgraph_for_context
        sg = {
            "nodes": [{"node_id": "auth.py::fn", "node_type": "FUNCTION"}],
            "edges": [{"src": "auth.py::fn", "dst": "auth.py", "edge_type": "DEFINED_IN"}],
        }
        result = format_subgraph_for_context(sg)
        assert "auth.py::fn" in result
