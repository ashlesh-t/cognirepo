# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""
tests/test_graph_repair.py — COGNIREPO-201: `cognirepo graph repair` CLI.

Exercises _cmd_graph_repair() against a real KnowledgeGraph (isolated_cognirepo
fixture chdirs into tmp_path), matching TC-201-1's dry-run-by-default / --apply flow.
"""
from __future__ import annotations


class TestGraphRepair:
    def test_dry_run_reports_without_mutating(self, isolated_cognirepo, capsys):
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType
        from interface.cli.main import _cmd_graph_repair

        kg = KnowledgeGraph()
        kg.add_node("gone.py", NodeType.FILE)
        kg.add_node("gone.py::stale", NodeType.FUNCTION, file="gone.py")
        kg.add_edge("gone.py::stale", "gone.py", EdgeType.DEFINED_IN)
        kg.save()

        code = _cmd_graph_repair(apply=False)
        out = capsys.readouterr().out

        assert code == 0
        assert "gone.py" in out
        assert "Dry run" in out

        # Nothing was mutated — reload from disk and confirm the node survives.
        kg2 = KnowledgeGraph()
        assert kg2.node_exists("gone.py")
        assert kg2.node_exists("gone.py::stale")

    def test_apply_prunes_danglers_only(self, isolated_cognirepo, capsys):
        """AC3: --apply removes danglers only; orphan CONCEPTs untouched; prints counts."""
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType
        from interface.cli.main import _cmd_graph_repair

        kg = KnowledgeGraph()
        with open("live.py", "w", encoding="utf-8") as f:
            f.write("def keep(): pass\n")
        kg.add_node("live.py", NodeType.FILE)
        kg.add_node("live.py::keep", NodeType.FUNCTION, file="live.py")
        kg.add_edge("live.py::keep", "live.py", EdgeType.DEFINED_IN)

        kg.add_node("gone.py", NodeType.FILE)
        kg.add_node("gone.py::stale", NodeType.FUNCTION, file="gone.py")
        kg.add_edge("gone.py::stale", "gone.py", EdgeType.DEFINED_IN)

        kg.add_node("orphan_concept", NodeType.CONCEPT, unresolved=True)
        kg.save()

        code = _cmd_graph_repair(apply=True)
        out = capsys.readouterr().out

        assert code == 0
        assert "Removed 2 node(s)" in out  # gone.py + gone.py::stale

        kg2 = KnowledgeGraph()
        assert kg2.node_exists("live.py") and kg2.node_exists("live.py::keep")
        assert not kg2.node_exists("gone.py") and not kg2.node_exists("gone.py::stale")
        assert kg2.node_exists("orphan_concept")

    def test_no_dangling_files_reports_clean(self, isolated_cognirepo, capsys):
        from data.graph.knowledge_graph import KnowledgeGraph
        from interface.cli.main import _cmd_graph_repair

        KnowledgeGraph().save()

        code = _cmd_graph_repair(apply=False)
        out = capsys.readouterr().out

        assert code == 0
        assert "no dangling file nodes found" in out
