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


class TestShutdownFlush:
    """COGNIREPO-D05: a pending debounced event must be flushed before the
    observer stops — both real shutdown call sites (foreground `cognirepo
    watch` and the MCP-launched background watcher) delegate to the same
    interface.cli.main._flush_and_stop_observer() helper.
    """

    def test_flush_and_stop_observer_flushes_pending_before_stop(self, tmp_path):
        from interface.cli.main import _flush_and_stop_observer

        handler, indexer, kg, behaviour = _make_handler(tmp_path, debounce_ms=5000)
        f = tmp_path / "auth.py"
        f.write_text("def verify_token(): pass")
        handler.on_modified(FileModifiedEvent(str(f)))
        assert indexer.index_file.call_count == 0  # still inside the debounce window

        obs = MagicMock()
        obs._cognirepo_handler = handler

        _flush_and_stop_observer(obs)

        # The queued edit was indexed (flushed) before the observer was stopped.
        indexer.index_file.assert_called_once()
        indexer.save.assert_called_once()
        obs.stop.assert_called_once()
        obs.join.assert_called_once()

    def test_flush_and_stop_observer_tolerates_missing_handler(self):
        """An observer without _cognirepo_handler (e.g. a bare test double) still stops cleanly."""
        from interface.cli.main import _flush_and_stop_observer

        obs = MagicMock(spec=["stop", "join"])
        _flush_and_stop_observer(obs)
        obs.stop.assert_called_once()
        obs.join.assert_called_once()


class TestLastWatcherReindexAuditTrail:
    """COGNIREPO-D12: flush() must leave a durable, mode-independent trail of
    watcher-driven reindex activity — previously only a bare print(), invisible
    outside daemon mode."""

    def test_flush_writes_last_watcher_reindex_json(self, tmp_path):
        import os
        import json
        from watchdog.events import FileDeletedEvent

        # get_cognirepo_dir_for_repo() prefers a LOCAL .cognirepo/ under
        # repo_root over the global fallback — create it so the write lands
        # in the isolated tmp_path, not the real ~/.cognirepo/.
        (tmp_path / ".cognirepo").mkdir(exist_ok=True)

        handler, indexer, kg, behaviour = _make_handler(tmp_path, debounce_ms=100)
        f = tmp_path / "auth.py"
        f.write_text("def verify_token(): pass")
        g = tmp_path / "old.py"
        g.write_text("def stale(): pass")

        handler.on_modified(FileModifiedEvent(str(f)))
        handler.on_deleted(FileDeletedEvent(str(g)))
        time.sleep(0.3)

        log_path = tmp_path / ".cognirepo" / "index" / "last_watcher_reindex.json"
        assert log_path.exists()
        record = json.loads(log_path.read_text(encoding="utf-8"))
        assert record["session_id"] == "test"
        assert "timestamp" in record
        assert os.path.relpath(str(f), str(tmp_path)) in record["reindexed"]
        assert os.path.relpath(str(g), str(tmp_path)) in record["removed"]

    def test_second_flush_overwrites_not_appends(self, tmp_path):
        import json

        (tmp_path / ".cognirepo").mkdir(exist_ok=True)

        handler, indexer, kg, behaviour = _make_handler(tmp_path, debounce_ms=100)
        f1 = tmp_path / "one.py"
        f1.write_text("def one(): pass")
        f2 = tmp_path / "two.py"
        f2.write_text("def two(): pass")

        handler.on_modified(FileModifiedEvent(str(f1)))
        time.sleep(0.3)
        handler.on_modified(FileModifiedEvent(str(f2)))
        time.sleep(0.3)

        log_path = tmp_path / ".cognirepo" / "index" / "last_watcher_reindex.json"
        record = json.loads(log_path.read_text(encoding="utf-8"))
        # Only the most recent batch — not both, and not growing unbounded.
        assert any("two.py" in p for p in record["reindexed"])
        assert not any("one.py" in p for p in record["reindexed"])
