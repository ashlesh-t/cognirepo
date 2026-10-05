# pylint: disable=missing-docstring, import-outside-toplevel, too-few-public-methods, protected-access
# pylint: disable=redefined-outer-name, unused-argument, duplicate-code
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_incremental_base_guard.py — COGNIREPO-122.

An incremental run (index-repo --files / --changed-only, the watcher) must never publish a
graph that is not a superset of the previous one.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

from data.graph.knowledge_graph import KnowledgeGraph, NodeType


def _graph_path() -> str:
    from data.graph.knowledge_graph import _graph_file
    return _graph_file()


def _full_graph(files: int = 10, marked: bool = True) -> KnowledgeGraph:
    kg = KnowledgeGraph()
    for i in range(files):
        kg.add_node(f"pkg/m{i}.py", NodeType.FILE)
        kg.add_node(f"pkg/m{i}.py::f", NodeType.FUNCTION, file=f"pkg/m{i}.py")
    if marked:
        kg.mark_complete()
    return kg


class TestIncrementalBaseStatus:
    def test_marked_complete_is_a_safe_base(self, isolated_cognirepo):
        assert _full_graph().incremental_base_status(10) == (True, "")

    def test_marker_survives_save_and_reload(self, isolated_cognirepo):
        _full_graph().save()
        assert KnowledgeGraph().incremental_base_status(None) == (True, "")

    def test_empty_graph_is_refused(self, isolated_cognirepo):
        ok, reason = KnowledgeGraph().incremental_base_status(500)
        assert not ok and "no graph on disk" in reason

    def test_locked_graph_is_refused(self, isolated_cognirepo):
        kg = _full_graph()
        kg._locked = True
        ok, reason = kg.incremental_base_status(10)
        assert not ok and "cannot be decrypted" in reason

    def test_unmarked_fragment_is_refused(self, isolated_cognirepo):
        """The #122 incident: a 2-file graph next to an AST index of 400 files."""
        frag = _full_graph(files=2, marked=False)
        ok, reason = frag.incremental_base_status(400)
        assert not ok and "fragment" in reason

    def test_unmarked_legacy_graph_that_covers_the_repo_is_accepted(self, isolated_cognirepo):
        legacy = _full_graph(files=30, marked=False)  # written before the marker existed
        assert legacy.incremental_base_status(40) == (True, "")

    def test_unmarked_graph_without_ast_index_cannot_be_verified(self, isolated_cognirepo):
        ok, reason = _full_graph(files=30, marked=False).incremental_base_status(0)
        assert not ok and "no AST index" in reason


class TestMarkerIsJournaled:
    def test_marker_survives_a_full_index_whose_final_save_never_ran(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        kg.begin_journal()
        kg.add_node("a.py", NodeType.FILE)
        kg.mark_complete()
        kg.end_journal()                      # no save(): breaker trip / kill
        assert not os.path.exists(_graph_path())
        assert KnowledgeGraph().G.graph.get("complete") is True

    def test_marker_is_kept_when_a_stale_save_rebases(self, isolated_cognirepo):
        indexer, watcher = KnowledgeGraph(), KnowledgeGraph()
        indexer.add_node("a.py", NodeType.FILE)
        indexer.mark_complete()
        indexer.save()
        watcher.add_node("w.py", NodeType.FILE)
        watcher.save()                        # rebases onto the complete graph
        assert KnowledgeGraph().G.graph.get("complete") is True


class TestFullIndexMarksComplete:
    def _repo(self, tmp_path):
        repo = tmp_path / "proj"
        repo.mkdir()
        (repo / "a.py").write_text("def f():\n    return 1\n")
        (repo / "b.py").write_text("from a import f\n\ndef g():\n    return f()\n")
        return repo

    def test_index_repo_stamps_the_marker(self, isolated_cognirepo, tmp_path):
        from intelligence.indexer.ast_indexer import ASTIndexer
        kg = KnowledgeGraph()
        ASTIndexer(graph=kg).index_repo(str(self._repo(tmp_path)), embed=False)
        assert kg.G.graph.get("complete") is True
        kg.save()
        assert KnowledgeGraph().G.graph.get("complete") is True

    def test_skip_graph_does_not_claim_a_complete_graph(self, isolated_cognirepo, tmp_path):
        from intelligence.indexer.ast_indexer import ASTIndexer
        kg = KnowledgeGraph()
        ASTIndexer(graph=kg).index_repo(str(self._repo(tmp_path)), embed=False, skip_graph=True)
        assert not kg.G.graph.get("complete")


def _run_cli(monkeypatch, *argv):
    from interface.cli import main as cli
    monkeypatch.setattr(sys, "argv", ["cognirepo", *argv])
    cli._main()


class TestCliIncrementalPaths:
    def _file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "new.py").write_text("def brand_new():\n    return 1\n")
        return "new.py"

    def test_files_on_a_missing_graph_refuses_and_writes_nothing(
            self, isolated_cognirepo, tmp_path, monkeypatch, capsys):
        rel = self._file(tmp_path, monkeypatch)
        assert not os.path.exists(_graph_path())
        with pytest.raises(SystemExit) as exc:
            _run_cli(monkeypatch, "index-repo", "--files", rel)
        assert exc.value.code == 2
        assert not os.path.exists(_graph_path()), "a fragment graph must not be published"
        err = capsys.readouterr().err
        assert "not updating the graph" in err and "index-repo ." in err

    def test_files_does_not_replace_a_full_graph_with_a_fragment(
            self, isolated_cognirepo, tmp_path, monkeypatch):
        rel = self._file(tmp_path, monkeypatch)
        _full_graph(files=40).save()
        before = KnowledgeGraph().G.number_of_nodes()
        _run_cli(monkeypatch, "index-repo", "--files", rel)
        after = KnowledgeGraph()
        assert after.G.number_of_nodes() >= before          # superset, never a shrink
        assert after.G.has_node("pkg/m39.py") and after.G.has_node("new.py")
        assert after.G.graph.get("complete") is True

    def test_files_on_an_unmarked_fragment_refuses(
            self, isolated_cognirepo, tmp_path, monkeypatch, capsys):
        """Quarantine -> fragment -> next hook run must not keep growing the fragment."""
        rel = self._file(tmp_path, monkeypatch)
        _full_graph(files=2, marked=False).save()
        from intelligence.indexer import ast_indexer
        monkeypatch.setattr(ast_indexer.ASTIndexer, "indexed_file_count", lambda self: 400)
        monkeypatch.setattr(ast_indexer.ASTIndexer, "load", lambda self: None)
        with pytest.raises(SystemExit) as exc:
            _run_cli(monkeypatch, "index-repo", "--files", rel)
        assert exc.value.code == 2
        assert KnowledgeGraph().G.number_of_nodes() == 4    # untouched
        assert "fragment" in capsys.readouterr().err

    def test_changed_only_refuses_on_a_missing_graph(
            self, isolated_cognirepo, tmp_path, monkeypatch, capsys):
        import subprocess
        monkeypatch.chdir(tmp_path)
        git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
        subprocess.run(["git", "init", "-q"], check=True)
        (tmp_path / "base.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run([*git, "commit", "-qm", "init"], check=True)
        (tmp_path / "base.py").write_text("x = 2\n")  # a tracked file changed since HEAD
        with pytest.raises(SystemExit) as exc:
            _run_cli(monkeypatch, "index-repo", "--changed-only")
        assert exc.value.code == 2
        assert not os.path.exists(_graph_path())
        assert "--changed-only" in capsys.readouterr().err


class TestWatcherGuard:
    def _handler(self, graph):
        from intelligence.indexer.file_watcher import RepoFileHandler
        indexer = MagicMock()
        indexer.index_data = {"files": {f"f{i}.py": {} for i in range(400)}, "reverse_index": {}}
        return RepoFileHandler("/repo", indexer, graph, MagicMock(), "test", debounce_ms=0)

    def test_watcher_does_not_save_a_missing_graph_and_warns_once(
            self, isolated_cognirepo, capsys):
        kg = KnowledgeGraph()
        kg.save = MagicMock()
        handler = self._handler(kg)
        handler._save_graph()
        handler._save_graph()
        kg.save.assert_not_called()
        assert capsys.readouterr().err.count("not saving the graph") == 1

    def test_watcher_saves_once_the_graph_is_a_complete_base(self, isolated_cognirepo):
        kg = _full_graph()
        kg.save = MagicMock()
        self._handler(kg)._save_graph()
        kg.save.assert_called_once()
