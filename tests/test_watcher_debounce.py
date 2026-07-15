# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_watcher_debounce.py — COGNIREPO-102 acceptance tests.

AC1: 5 modify events for one file within the debounce window collapse to
     exactly one index_file call and one indexer.save()/graph.save().
AC3: debounce window is configurable via debounce_ms; 0 disables batching
     and restores the old synchronous per-event behavior.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

from watchdog.events import FileModifiedEvent


def _make_handler(tmp_path, debounce_ms):
    from intelligence.indexer.file_watcher import RepoFileHandler
    from data.graph.knowledge_graph import KnowledgeGraph
    import networkx as nx

    kg = KnowledgeGraph.__new__(KnowledgeGraph)
    kg.G = nx.DiGraph()
    kg.nodes_for_file = MagicMock(return_value=[])
    kg.remove_node_edges = MagicMock()
    kg.save = MagicMock()

    indexer = MagicMock()
    indexer.faiss_index = None
    indexer.index_data = {"files": {}, "reverse_index": {}}
    indexer.index_file = MagicMock()
    indexer._build_reverse_index = MagicMock()
    indexer.save = MagicMock()

    behaviour = MagicMock()

    handler = RepoFileHandler(
        repo_root=str(tmp_path),
        indexer=indexer,
        graph=kg,
        behaviour=behaviour,
        session_id="test",
        debounce_ms=debounce_ms,
    )
    return handler, indexer, kg, behaviour


class TestDebounceBatching:
    def test_five_modify_events_collapse_to_one_save(self, tmp_path):
        """AC1: a burst of 5 modify events for the same file → one index_file + one save."""
        handler, indexer, kg, behaviour = _make_handler(tmp_path, debounce_ms=100)
        f = tmp_path / "auth.py"
        f.write_text("def verify_token(): pass")

        for _ in range(5):
            handler.on_modified(FileModifiedEvent(str(f)))

        assert indexer.index_file.call_count == 0  # still pending, timer not yet fired
        time.sleep(0.3)

        indexer.index_file.assert_called_once()
        indexer.save.assert_called_once()
        kg.save.assert_called_once()
        behaviour.save.assert_called_once()

    def test_debounce_zero_processes_synchronously(self, tmp_path):
        """AC3: debounce_ms=0 disables batching — each event processed immediately."""
        handler, indexer, kg, behaviour = _make_handler(tmp_path, debounce_ms=0)
        f = tmp_path / "auth.py"
        f.write_text("def verify_token(): pass")

        for _ in range(3):
            handler.on_modified(FileModifiedEvent(str(f)))

        assert indexer.index_file.call_count == 3
        assert indexer.save.call_count == 3
        assert kg.save.call_count == 3

    def test_debounce_window_configurable(self, tmp_path):
        """AC3: a custom debounce_ms is honored (batch flushes only after the window elapses)."""
        handler, indexer, _, _ = _make_handler(tmp_path, debounce_ms=150)
        f = tmp_path / "auth.py"
        f.write_text("def verify_token(): pass")

        handler.on_modified(FileModifiedEvent(str(f)))
        time.sleep(0.05)
        assert indexer.index_file.call_count == 0  # window hasn't elapsed yet

        time.sleep(0.3)
        assert indexer.index_file.call_count == 1

    def test_flush_is_idempotent_when_nothing_pending(self, tmp_path):
        """flush() with no queued events is a no-op (used by stop_watching() on shutdown)."""
        handler, indexer, kg, behaviour = _make_handler(tmp_path, debounce_ms=100)

        handler.flush()

        indexer.index_file.assert_not_called()
        indexer.save.assert_not_called()
        kg.save.assert_not_called()

    def test_flush_processes_pending_immediately(self, tmp_path):
        """flush() called directly (e.g. from stop_watching()) processes queued events without waiting."""
        handler, indexer, kg, behaviour = _make_handler(tmp_path, debounce_ms=5000)
        f = tmp_path / "auth.py"
        f.write_text("def verify_token(): pass")

        handler.on_modified(FileModifiedEvent(str(f)))
        assert indexer.index_file.call_count == 0

        handler.flush()

        indexer.index_file.assert_called_once()
        indexer.save.assert_called_once()
