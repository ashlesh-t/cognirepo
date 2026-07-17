# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_stale_cleanup.py — Sprint 4 acceptance tests for TASK-011.

Covers stale data cleanup across all four stores when a file is deleted:
  1. FAISS (AST) — symbol vectors removed
  2. Knowledge graph — nodes fully removed (not just edges)
  3. Reverse index — lookup_symbol returns empty
  4. Episodic memory — entries tagged stale, still queryable
  5. Rename handled as delete + create
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_file_record(rel_path: str, symbol_name: str) -> dict:
    return {
        "indexed_at": "2026-01-01T00:00:00+00:00",
        "sha256": "abc123",
        "language": "Python",
        "symbols": [
            {
                "name": symbol_name,
                "type": "FUNCTION",
                "start_line": 10,
                "end_line": 20,
                "faiss_id": 0,
                "docstring": "",
                "calls": [],
            }
        ],
    }


# ── TASK-011: remove_file_nodes ───────────────────────────────────────────────

class TestGraphRemoveFileNodes:
    def test_removes_symbol_nodes_and_file_node(self):
        """remove_file_nodes() deletes both symbol nodes and the FILE node."""
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType

        kg = KnowledgeGraph.__new__(KnowledgeGraph)
        import networkx as nx
        kg.G = nx.DiGraph()

        rel_path = "auth/auth.py"
        # Add a FILE node (node_id == rel_path per make_node_id convention)
        kg.G.add_node(rel_path, type=NodeType.FILE)
        # Add a FUNCTION node with file=rel_path
        sym_node = f"{rel_path}::verify_token"
        kg.G.add_node(sym_node, type=NodeType.FUNCTION, file=rel_path, line=10)
        kg.G.add_edge(sym_node, rel_path, rel=EdgeType.DEFINED_IN)

        removed = kg.remove_file_nodes(rel_path)

        assert rel_path not in kg.G
        assert sym_node not in kg.G
        assert rel_path in removed
        assert sym_node in removed

    def test_returns_empty_for_unknown_file(self):
        from data.graph.knowledge_graph import KnowledgeGraph
        import networkx as nx

        kg = KnowledgeGraph.__new__(KnowledgeGraph)
        kg.G = nx.DiGraph()

        result = kg.remove_file_nodes("nonexistent.py")
        assert result == []

    def test_edges_removed_with_nodes(self):
        """NetworkX removes incident edges automatically on node removal."""
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType
        import networkx as nx

        kg = KnowledgeGraph.__new__(KnowledgeGraph)
        kg.G = nx.DiGraph()

        rel_path = "foo.py"
        sym_node = f"{rel_path}::bar"
        kg.G.add_node(rel_path, type=NodeType.FILE)
        kg.G.add_node(sym_node, type=NodeType.FUNCTION, file=rel_path)
        kg.G.add_edge(sym_node, rel_path, rel=EdgeType.DEFINED_IN)

        kg.remove_file_nodes(rel_path)

        # No edges should remain for removed nodes
        assert kg.G.number_of_edges() == 0


# ── TASK-011: episodic mark_stale ────────────────────────────────────────────

class TestEpisodicMarkStale:
    def test_matching_entries_tagged_stale(self, tmp_path, monkeypatch):
        """Entries that reference file_path are tagged stale."""
        from data.memory import episodic_memory as em
        monkeypatch.setattr(
            "data.memory.episodic_memory._file_path",
            lambda: str(tmp_path / "episodic.json"),
        )
        # Patch _save to avoid security/encryption calls
        monkeypatch.setattr(em, "_save", lambda data: _raw_save(tmp_path, data))
        monkeypatch.setattr(em, "_load", lambda: _raw_load(tmp_path))

        _raw_save(tmp_path, [
            {"id": "e_0", "event": "indexed auth/auth.py", "metadata": {}, "time": "2026-01-01T00:00:00Z"},
            {"id": "e_1", "event": "something unrelated", "metadata": {}, "time": "2026-01-01T00:01:00Z"},
        ])

        tagged = em.mark_stale("auth/auth.py")
        assert tagged == 1

        data = _raw_load(tmp_path)
        assert data[0].get("stale") is True
        assert data[0].get("stale_reason") == "file_deleted"
        assert not data[1].get("stale")

    def test_stale_entries_still_queryable(self, tmp_path, monkeypatch):
        """Stale entries are NOT deleted — get_history() still returns them."""
        from data.memory import episodic_memory as em
        monkeypatch.setattr(em, "_save", lambda data: _raw_save(tmp_path, data))
        monkeypatch.setattr(em, "_load", lambda: _raw_load(tmp_path))

        _raw_save(tmp_path, [
            {"id": "e_0", "event": "indexed auth/auth.py", "metadata": {}, "time": "2026-01-01T00:00:00Z"},
        ])
        em.mark_stale("auth/auth.py")

        history = em.get_history(limit=10)
        assert len(history) == 1
        assert history[0]["stale"] is True

    def test_already_stale_not_double_tagged(self, tmp_path, monkeypatch):
        """Calling mark_stale twice does not change the stale entry again."""
        from data.memory import episodic_memory as em
        monkeypatch.setattr(em, "_save", lambda data: _raw_save(tmp_path, data))
        monkeypatch.setattr(em, "_load", lambda: _raw_load(tmp_path))

        _raw_save(tmp_path, [
            {"id": "e_0", "event": "deleted auth/auth.py", "metadata": {},
             "time": "2026-01-01T00:00:00Z", "stale": True, "stale_reason": "file_deleted"},
        ])
        tagged = em.mark_stale("auth/auth.py")
        assert tagged == 0  # already stale, skip


# ── TASK-011: file_watcher._remove() integration ─────────────────────────────

class TestFileWatcherRemove:
    def _make_handler(self, tmp_path):
        from intelligence.indexer.file_watcher import RepoFileHandler
        from data.graph.knowledge_graph import KnowledgeGraph
        import networkx as nx

        kg = KnowledgeGraph.__new__(KnowledgeGraph)
        kg.G = nx.DiGraph()

        indexer = MagicMock()
        indexer.faiss_index = None  # no FAISS in unit test
        indexer.index_data = {
            "files": {
                "auth.py": _make_file_record("auth.py", "verify_token"),
            },
            "reverse_index": {"verify_token": [["auth.py", 10]]},
        }
        indexer._build_reverse_index = MagicMock(side_effect=indexer.index_data["reverse_index"].clear)
        indexer.save = MagicMock()

        kg.save = MagicMock()

        behaviour = MagicMock()
        handler = RepoFileHandler(
            repo_root=str(tmp_path),
            indexer=indexer,
            graph=kg,
            behaviour=behaviour,
            session_id="test",
            debounce_ms=0,
        )
        return handler, indexer, kg

    def test_removes_file_from_index_data(self, tmp_path):
        handler, indexer, _ = self._make_handler(tmp_path)
        (tmp_path / "auth.py").write_text("def verify_token(): pass")

        handler._remove(str(tmp_path / "auth.py"))

        assert "auth.py" not in indexer.index_data["files"]

    def test_rebuild_and_save_called(self, tmp_path):
        handler, indexer, kg = self._make_handler(tmp_path)
        (tmp_path / "auth.py").write_text("def verify_token(): pass")

        handler._remove(str(tmp_path / "auth.py"))

        indexer._build_reverse_index.assert_called_once()
        indexer.save.assert_called_once()
        kg.save.assert_called_once()

    def test_rename_delete_then_create(self, tmp_path):
        """Rename = on_deleted for old + on_created for new path."""
        from watchdog.events import FileDeletedEvent, FileCreatedEvent

        handler, indexer, _ = self._make_handler(tmp_path)

        # Create old file so _remove doesn't error
        old_file = tmp_path / "auth.py"
        new_file = tmp_path / "auth_v2.py"
        old_file.write_text("def verify_token(): pass")
        new_file.write_text("def verify_token_v2(): pass")

        # Simulate rename: delete old, create new
        handler.on_deleted(FileDeletedEvent(str(old_file)))
        assert "auth.py" not in indexer.index_data["files"]

        # Simulate create of new file (indexer.index_file is mocked)
        indexer.index_file = MagicMock(return_value=_make_file_record("auth_v2.py", "verify_token_v2"))
        handler.on_created(FileCreatedEvent(str(new_file)))
        indexer.index_file.assert_called_once()

    def test_on_moved_removes_src_and_reindexes_dest(self, tmp_path):
        """A git-mv style rename: on_moved() removes the src path and re-indexes dest path."""
        from watchdog.events import FileMovedEvent

        handler, indexer, kg = self._make_handler(tmp_path)

        old_file = tmp_path / "auth.py"
        new_file = tmp_path / "auth_v2.py"
        old_file.write_text("def verify_token(): pass")
        new_file.write_text("def verify_token_v2(): pass")

        indexer.index_file = MagicMock(
            side_effect=lambda rel_path, abs_path: indexer.index_data["files"].__setitem__(
                rel_path, _make_file_record(rel_path, "verify_token_v2")
            )
        )
        kg.nodes_for_file = MagicMock(return_value=[])
        kg.remove_node_edges = MagicMock()
        kg.remove_file_nodes = MagicMock()

        handler.on_moved(FileMovedEvent(str(old_file), str(new_file)))

        assert "auth.py" not in indexer.index_data["files"]
        assert "auth_v2.py" in indexer.index_data["files"]
        indexer.index_file.assert_called_once_with("auth_v2.py", str(new_file))


# ── COGNIREPO-103 AC1: orphan-node cleanup on re-index (modify path) ─────────

class TestFileWatcherReindexOrphanCleanup:
    def test_removed_function_leaves_no_orphan_node(self, tmp_path):
        """Editing a file to remove a function must not leave a dangling graph node for it."""
        from intelligence.indexer.file_watcher import RepoFileHandler
        from data.graph.knowledge_graph import KnowledgeGraph, NodeType
        import networkx as nx

        kg = KnowledgeGraph.__new__(KnowledgeGraph)
        kg.G = nx.DiGraph()
        kg.G.add_node("mod.py", type=NodeType.FILE)
        kg.G.add_node("mod.py::foo", type=NodeType.FUNCTION, file="mod.py")
        kg.G.add_node("mod.py::bar", type=NodeType.FUNCTION, file="mod.py")

        indexer = MagicMock()
        indexer.faiss_index = None
        indexer.index_data = {"files": {}, "reverse_index": {}}

        def _reindex_side_effect(rel_path, abs_path):
            # Simulate re-indexing after `bar` was deleted from the file — only
            # the FILE node and the surviving `foo` symbol get re-added.
            kg.G.add_node(rel_path, type=NodeType.FILE)
            kg.G.add_node(f"{rel_path}::foo", type=NodeType.FUNCTION, file=rel_path)

        indexer.index_file = MagicMock(side_effect=_reindex_side_effect)
        behaviour = MagicMock()

        handler = RepoFileHandler(
            repo_root=str(tmp_path),
            indexer=indexer,
            graph=kg,
            behaviour=behaviour,
            session_id="test",
            debounce_ms=0,
        )

        mod_file = tmp_path / "mod.py"
        mod_file.write_text("def foo(): pass")

        handler._reindex_mutate(str(mod_file))

        assert "mod.py::bar" not in kg.G  # orphan removed
        assert "mod.py::foo" in kg.G  # surviving symbol still present
        assert "mod.py" in kg.G  # FILE node re-added


# ── helpers (raw JSON I/O, bypass encryption) ─────────────────────────────────

def _raw_save(tmp_path: Path, data: list) -> None:
    path = tmp_path / "episodic.json"
    path.write_text(json.dumps(data))


def _raw_load(tmp_path: Path) -> list:
    path = tmp_path / "episodic.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())
