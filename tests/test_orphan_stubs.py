# pylint: disable=missing-docstring, import-outside-toplevel, too-few-public-methods, protected-access
# pylint: disable=redefined-outer-name, unused-argument, duplicate-code
# SPDX-FileCopyrightText: 2026 Ashlesh T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_orphan_stubs.py — COGNIREPO-128.

Deleting a file must not leave an orphan, unresolved, degree-0 ``symbol::<name>`` stub: the
symbol's own DEFINED_IN edge to the FILE node being removed is not an outside reference.
"""
from __future__ import annotations

from data.graph.knowledge_graph import EdgeType, KnowledgeGraph, NodeType


def _file(kg: KnowledgeGraph, path: str, *funcs: str) -> list[str]:
    kg.add_node(path, NodeType.FILE)
    ids = []
    for fn in funcs:
        nid = f"{path}::{fn}"
        kg.add_node(nid, NodeType.FUNCTION, file=path)
        kg.add_edge(nid, path, EdgeType.DEFINED_IN)
        ids.append(nid)
    return ids


def _calls(kg: KnowledgeGraph, caller: str, callee: str) -> None:
    """Call edges exactly as the indexer writes them: bidirectional, caller→callee is CALLED_BY."""
    if not kg.G.has_node(callee):
        kg.add_node(callee, NodeType.CONCEPT)
    kg.add_edge(caller, callee, EdgeType.CALLED_BY)
    kg.add_edge(callee, caller, EdgeType.CALLS)


def _stubs(kg: KnowledgeGraph) -> list[str]:
    return sorted(n for n in kg.G if n.startswith("symbol::"))


class TestNoStubForAnUnreferencedSymbol:
    def test_deleting_a_file_with_an_unreferenced_function_leaves_no_stub(self, isolated_cognirepo):
        """The exact scenario from the issue: a one-function probe file."""
        kg = KnowledgeGraph()
        _file(kg, "probe.py", "cognirepo_probe_fn_8841")
        removed = kg.remove_file_nodes("probe.py")
        assert sorted(removed) == ["probe.py", "probe.py::cognirepo_probe_fn_8841"]
        assert _stubs(kg) == []
        assert kg.G.number_of_nodes() == 0

    def test_internal_calls_within_the_file_do_not_create_a_stub(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        a, b = _file(kg, "m.py", "a", "b")
        _calls(kg, a, b)                           # a calls b — both leave with the file
        kg.remove_file_nodes("m.py")
        assert _stubs(kg) == [] and kg.G.number_of_nodes() == 0

    def test_a_class_with_an_internal_subclass_leaves_no_stub(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        kg.add_node("m.py", NodeType.FILE)
        for n in ("Base", "Child"):
            kg.add_node(f"m.py::{n}", NodeType.CLASS, file="m.py")
            kg.add_edge(f"m.py::{n}", "m.py", EdgeType.DEFINED_IN)
        kg.add_edge("m.py::Child", "m.py::Base", EdgeType.INHERITS)
        kg.remove_file_nodes("m.py")
        assert _stubs(kg) == []


class TestOutsideReferencesAreStillPreserved:
    """The D10 behaviour this must not regress."""

    def test_a_caller_in_another_file_keeps_its_edge_via_a_stub(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        (target,) = _file(kg, "lib.py", "helper")
        (caller,) = _file(kg, "app.py", "main")
        _calls(kg, caller, target)
        kg.remove_file_nodes("lib.py")
        assert _stubs(kg) == ["symbol::helper"]
        assert kg.G.nodes["symbol::helper"]["unresolved"] is True
        assert kg.G.has_edge(caller, "symbol::helper") and kg.G.has_edge("symbol::helper", caller)

    def test_a_subclass_in_another_file_keeps_its_inherits_edge(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        kg.add_node("base.py", NodeType.FILE)
        kg.add_node("base.py::Base", NodeType.CLASS, file="base.py")
        kg.add_edge("base.py::Base", "base.py", EdgeType.DEFINED_IN)
        kg.add_node("sub.py", NodeType.FILE)
        kg.add_node("sub.py::Sub", NodeType.CLASS, file="sub.py")
        kg.add_edge("sub.py::Sub", "sub.py", EdgeType.DEFINED_IN)
        kg.add_edge("sub.py::Sub", "base.py::Base", EdgeType.INHERITS)
        kg.remove_file_nodes("base.py")
        assert kg.G.has_edge("sub.py::Sub", "symbol::Base")

    def test_only_outside_edges_are_copied_onto_the_stub(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        helper, other = _file(kg, "lib.py", "helper", "other")
        (caller,) = _file(kg, "app.py", "main")
        _calls(kg, helper, other)                            # internal call
        _calls(kg, caller, helper)                           # external caller
        kg.remove_file_nodes("lib.py")
        assert set(kg.G.successors(caller)) >= {"symbol::helper"}
        assert "lib.py" not in kg.G and "lib.py::other" not in kg.G
        assert "symbol::other" not in kg.G


class TestStubsOrphanedByTheRemoval:
    def test_deleting_the_only_caller_drops_the_stub_it_pointed_at(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        (caller,) = _file(kg, "app.py", "main")
        kg.add_node("symbol::missing_dep", NodeType.CONCEPT, unresolved=True)
        _calls(kg, caller, "symbol::missing_dep")
        kg.remove_file_nodes("app.py")
        assert _stubs(kg) == []

    def test_a_stub_that_still_has_another_caller_survives(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        (c1,) = _file(kg, "a.py", "f")
        (c2,) = _file(kg, "b.py", "g")
        kg.add_node("symbol::dep", NodeType.CONCEPT, unresolved=True)
        _calls(kg, c1, "symbol::dep")
        _calls(kg, c2, "symbol::dep")
        kg.remove_file_nodes("a.py")
        assert _stubs(kg) == ["symbol::dep"]

    def test_non_stub_concepts_are_never_swept(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        (caller,) = _file(kg, "a.py", "f")
        kg.add_node("concept::dynamic_dispatch", NodeType.CONCEPT)
        kg.add_edge(caller, "concept::dynamic_dispatch", EdgeType.RELATES_TO)
        kg.remove_file_nodes("a.py")
        assert "concept::dynamic_dispatch" in kg.G


class TestIntegritySweep:
    def _graph_with_leftovers(self):
        kg = KnowledgeGraph()
        kg.add_node("symbol::dead_one", NodeType.CONCEPT, unresolved=True)
        kg.add_node("symbol::dead_two", NodeType.CONCEPT, unresolved=True)
        (fn,) = _file(kg, "live.py", "f")
        kg.add_node("symbol::alive", NodeType.CONCEPT, unresolved=True)
        _calls(kg, fn, "symbol::alive")
        kg.add_node("unrelated_concept", NodeType.CONCEPT)         # not a symbol:: stub
        return kg

    def test_report_lists_degree_zero_stubs_only(self, isolated_cognirepo, tmp_path):
        report = self._graph_with_leftovers().integrity_report(str(tmp_path))
        assert sorted(report["orphan_stubs"]) == ["symbol::dead_one", "symbol::dead_two"]

    def test_remove_orphan_stubs_is_journaled(self, isolated_cognirepo):
        kg = self._graph_with_leftovers()
        kg.save()
        kg.begin_journal()
        removed = kg.remove_orphan_stubs()
        kg.end_journal()
        assert sorted(removed) == ["symbol::dead_one", "symbol::dead_two"]
        fresh = KnowledgeGraph()           # replays the journal over graph.pkl
        assert _stubs(fresh) == ["symbol::alive"] and "unrelated_concept" in fresh.G


class TestRepairAndDoctor:
    def _save_graph_with_leftovers(self):
        kg = KnowledgeGraph()
        kg.add_node("symbol::cognirepo_probe_fn_8841", NodeType.CONCEPT, unresolved=True)
        kg.add_node("keep_me", NodeType.CONCEPT)
        kg.mark_complete()
        kg.save()

    def test_graph_repair_dry_run_reports_stubs_without_changing_anything(self, isolated_cognirepo, capsys):
        from interface.cli.main import _cmd_graph_repair
        self._save_graph_with_leftovers()
        assert _cmd_graph_repair(apply=False) == 0
        out = capsys.readouterr().out
        assert "symbol::cognirepo_probe_fn_8841" in out and "Dry run" in out
        assert "symbol::cognirepo_probe_fn_8841" in KnowledgeGraph().G

    def test_graph_repair_apply_removes_stubs_and_keeps_other_concepts(self, isolated_cognirepo, capsys):
        from interface.cli.main import _cmd_graph_repair
        self._save_graph_with_leftovers()
        assert _cmd_graph_repair(apply=True) == 0
        assert "Removed 1 orphan symbol stub" in capsys.readouterr().out
        fresh = KnowledgeGraph()
        assert "symbol::cognirepo_probe_fn_8841" not in fresh.G and "keep_me" in fresh.G

    def test_graph_repair_clean_graph_message_unchanged(self, isolated_cognirepo, capsys):
        from interface.cli.main import _cmd_graph_repair
        KnowledgeGraph().save()
        assert _cmd_graph_repair(apply=False) == 0
        assert "no dangling file nodes found" in capsys.readouterr().out


class TestThroughTheRealIndexer:
    def test_index_then_delete_a_probe_file_leaves_no_stub(self, isolated_cognirepo, tmp_path, monkeypatch):
        """Mirrors the reproduction: index a one-function file, then the watcher removes it."""
        from intelligence.indexer.ast_indexer import ASTIndexer
        monkeypatch.chdir(tmp_path)
        (tmp_path / "probe.py").write_text("def cognirepo_probe_fn_8841():\n    return 1\n")
        kg = KnowledgeGraph()
        indexer = ASTIndexer(graph=kg)
        indexer.index_file("probe.py", str(tmp_path / "probe.py"))
        assert any(n.endswith("cognirepo_probe_fn_8841") for n in kg.G)
        kg.remove_file_nodes("probe.py")                   # what the watcher's _remove() does
        assert not any("cognirepo_probe_fn_8841" in n for n in kg.G), list(kg.G)
