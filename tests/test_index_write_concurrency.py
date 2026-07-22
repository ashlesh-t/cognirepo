# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_index_write_concurrency.py — COGNIREPO-D13/D14/D15/D16 regression tests.

Found by E2E-100-1 (epic ReliabilityGate-100): a burst-save against a live
watcher crashed two timer threads inside
ASTIndexer._atomic_json_dump -> os.replace(ast_index.json.tmp).

The pre-existing tests/test_watcher_debounce.py could not catch this: it
mocks indexer.save with a MagicMock, so the real writer is never exercised,
and every case asserts the debounce *collapse* property rather than
constructing overlapping flushes. These tests drive the real writer.
"""
from __future__ import annotations

import json
import os
import threading

import pytest


# ── D13: concurrent writers must not corrupt or crash ────────────────────────

class TestAtomicJsonDump:
    """_atomic_json_dump must be safe for N concurrent writers on one path."""

    def test_tmp_path_is_unique_per_writer(self, tmp_path):
        """The scratch filename must not be a pure function of the target path.

        A shared `path + '.tmp'` is the root cause of both observed failures:
        the loser of the rename race raises FileNotFoundError, and an
        interleaved open(tmp, 'w') truncates a file another writer is
        mid-dump into, promoting partial JSON into place.
        """
        from intelligence.indexer.ast_indexer import ASTIndexer

        target = str(tmp_path / "ast_index.json")
        seen: list[str] = []
        real_mkstemp = __import__("tempfile").mkstemp

        def _spy(*args, **kwargs):
            fd, name = real_mkstemp(*args, **kwargs)
            seen.append(name)
            return fd, name

        import intelligence.indexer.ast_indexer as mod
        mod.tempfile.mkstemp = _spy
        try:
            ASTIndexer._atomic_json_dump({"a": 1}, target)
            ASTIndexer._atomic_json_dump({"a": 2}, target)
        finally:
            mod.tempfile.mkstemp = real_mkstemp

        assert len(seen) == 2
        assert seen[0] != seen[1], "two writes reused the same scratch file"
        assert target + ".tmp" not in seen, "still using the deterministic tmp name"

    def test_concurrent_writers_leave_valid_json(self, tmp_path):
        """16 threads hammering one path: no exception, and the result parses.

        This is the direct regression for the E2E-100-1 crash.
        """
        from intelligence.indexer.ast_indexer import ASTIndexer

        target = str(tmp_path / "ast_index.json")
        # Large enough that a dump spans multiple write() syscalls, so an
        # interleaved truncation would actually be observable.
        payloads = [{"writer": i, "symbols": [f"sym_{i}_{n}" for n in range(2000)]}
                    for i in range(16)]
        errors: list[BaseException] = []
        barrier = threading.Barrier(len(payloads))

        def _write(p):
            try:
                barrier.wait()
                ASTIndexer._atomic_json_dump(p, target)
            except BaseException as exc:  # pylint: disable=broad-except
                errors.append(exc)

        threads = [threading.Thread(target=_write, args=(p,)) for p in payloads]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"concurrent writers raised: {errors!r}"

        with open(target, encoding="utf-8") as f:
            loaded = json.load(f)  # would raise on a truncated promote
        # Whichever writer won, its payload must be intact — not spliced.
        assert loaded["symbols"] == [f"sym_{loaded['writer']}_{n}" for n in range(2000)]

    def test_no_orphaned_tmp_files_after_concurrent_writes(self, tmp_path):
        """Scratch files must never survive a completed write."""
        from intelligence.indexer.ast_indexer import ASTIndexer

        target = str(tmp_path / "ast_index.json")
        errors: list[BaseException] = []

        def _write(i):
            try:
                ASTIndexer._atomic_json_dump({"i": i}, target)
            except BaseException as exc:  # pylint: disable=broad-except
                errors.append(exc)

        threads = [threading.Thread(target=_write, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Assert on the collected exceptions too: a thread that dies inside
        # os.replace() still leaves the directory tidy, so a leftovers-only
        # check would pass against the very bug this file exists to catch.
        assert not errors, f"concurrent writers raised: {errors!r}"
        leftovers = [n for n in os.listdir(tmp_path) if n.endswith(".tmp")]
        assert leftovers == [], f"orphaned scratch files: {leftovers}"

    def test_tmp_removed_when_serialization_fails(self, tmp_path):
        """A raise mid-dump must not strand a scratch file."""
        from intelligence.indexer.ast_indexer import ASTIndexer

        target = str(tmp_path / "ast_index.json")

        class _Unserializable:
            pass

        with pytest.raises(TypeError):
            ASTIndexer._atomic_json_dump({"bad": _Unserializable()}, target)

        assert [n for n in os.listdir(tmp_path) if n.endswith(".tmp")] == []
        assert not os.path.exists(target), "failed write must not create the target"

    def test_sweep_removes_legacy_and_orphaned_tmp(self, tmp_path):
        """load() clears scratch files stranded by a SIGKILL mid-write."""
        from intelligence.indexer.ast_indexer import ASTIndexer

        target = str(tmp_path / "ast_index.json")
        (tmp_path / "ast_index.json").write_text("{}")
        (tmp_path / "ast_index.json.tmp").write_text("partial")          # legacy fixed name
        (tmp_path / "ast_index.json.abc123.tmp").write_text("partial")   # mkstemp orphan
        (tmp_path / "keep.json").write_text("{}")

        ASTIndexer._sweep_stale_tmp(target)

        remaining = set(os.listdir(tmp_path))
        assert "ast_index.json.tmp" not in remaining
        assert "ast_index.json.abc123.tmp" not in remaining
        # The real index and unrelated files must survive the sweep.
        assert {"ast_index.json", "keep.json"} <= remaining


# ── D14: indexed_at must track every save, not only full index_repo runs ─────

class TestIndexedAtFreshness:
    def test_save_stamps_indexed_at(self, tmp_path, monkeypatch):
        """The watcher's incremental save must advance indexed_at.

        Previously only index_repo() stamped it, so graph_stats reported a
        two-hour-old last_indexed next to index_age_minutes=0.
        """
        import intelligence.indexer.ast_indexer as mod

        monkeypatch.setenv("COGNIREPO_DIR", str(tmp_path / ".cognirepo"))
        from core.config.paths import set_cognirepo_dir
        set_cognirepo_dir(str(tmp_path / ".cognirepo"))

        idx = mod.ASTIndexer.__new__(mod.ASTIndexer)
        idx.index_data = {"files": {}, "reverse_index": {}, "repo_root": str(tmp_path)}
        idx.faiss_index = None
        idx.faiss_meta = []

        monkeypatch.setattr(mod, "_write_manifest", lambda **_kw: None)
        monkeypatch.setattr(mod, "_now", lambda: "2026-07-22T10:00:00+00:00")
        idx.save()
        assert idx.index_data["indexed_at"] == "2026-07-22T10:00:00+00:00"

        monkeypatch.setattr(mod, "_now", lambda: "2026-07-22T12:30:00+00:00")
        idx.save()
        assert idx.index_data["indexed_at"] == "2026-07-22T12:30:00+00:00", \
            "incremental save left indexed_at frozen"

    def test_save_preserves_full_indexed_at(self, tmp_path, monkeypatch):
        """full_indexed_at marks the last COMPLETE sweep and must not move on save()."""
        import intelligence.indexer.ast_indexer as mod

        from core.config.paths import set_cognirepo_dir
        set_cognirepo_dir(str(tmp_path / ".cognirepo"))

        idx = mod.ASTIndexer.__new__(mod.ASTIndexer)
        idx.index_data = {
            "files": {}, "reverse_index": {}, "repo_root": str(tmp_path),
            "full_indexed_at": "2026-07-22T08:00:00+00:00",
        }
        idx.faiss_index = None
        idx.faiss_meta = []

        monkeypatch.setattr(mod, "_write_manifest", lambda **_kw: None)
        monkeypatch.setattr(mod, "_now", lambda: "2026-07-22T12:30:00+00:00")
        idx.save()

        assert idx.index_data["full_indexed_at"] == "2026-07-22T08:00:00+00:00"
        assert idx.index_data["indexed_at"] == "2026-07-22T12:30:00+00:00"


# ── D15: flush() serialization + partial-failure containment ─────────────────

def _make_handler(tmp_path, debounce_ms):
    """Mirrors tests/test_watcher_debounce.py::_make_handler."""
    from unittest.mock import MagicMock
    from intelligence.indexer.file_watcher import RepoFileHandler
    from data.graph.knowledge_graph import KnowledgeGraph
    import networkx as nx

    kg = KnowledgeGraph.__new__(KnowledgeGraph)
    kg.G = nx.DiGraph()
    kg.nodes_for_file = MagicMock(return_value=[])
    kg.remove_node_edges = MagicMock()
    kg.remove_file_nodes = MagicMock()
    kg.save = MagicMock()

    indexer = MagicMock()
    indexer.faiss_index = None
    indexer.index_data = {"files": {}, "reverse_index": {}}
    indexer.index_file = MagicMock(return_value={"symbols": []})
    indexer._build_reverse_index = MagicMock()
    indexer._resolve_call_stubs = MagicMock()
    indexer.save = MagicMock()

    handler = RepoFileHandler(
        repo_root=str(tmp_path), indexer=indexer, graph=kg,
        behaviour=MagicMock(), session_id="test", debounce_ms=debounce_ms,
    )
    return handler, indexer, kg


class TestFlushSerialization:
    def test_concurrent_flushes_never_overlap(self, tmp_path):
        """Two threads calling flush() must not run the batch body concurrently.

        Timer.cancel() is a no-op once the timer has fired, so a burst that
        outlasts the debounce window really does schedule a second flush
        while the first is still inside the seconds-long index+save section.
        """
        handler, indexer, _ = _make_handler(tmp_path, debounce_ms=5000)

        concurrent = []
        active = {"n": 0}
        gate = threading.Lock()

        def _slow_save():
            with gate:
                active["n"] += 1
                if active["n"] > 1:
                    concurrent.append(True)
            # Wide window for another thread to enter the body.
            threading.Event().wait(0.15)
            with gate:
                active["n"] -= 1

        indexer.save.side_effect = _slow_save

        # Each thread must queue its OWN event before flushing. A plain
        # "6 threads all call flush()" does not reproduce the race: the first
        # arrival drains _pending and the other five hit the `if not pending:
        # return` fast path, so only one thread ever reaches the save section.
        # The real sequence is a burst that keeps producing events while an
        # earlier flush is still inside index+save.
        def _queue_then_flush(i):
            f = tmp_path / f"mod_{i}.py"
            f.write_text("def f(): pass")
            handler._queue("reindex", str(f))
            handler.flush()

        threads = []
        for i in range(6):
            t = threading.Thread(target=_queue_then_flush, args=(i,))
            t.start()
            threads.append(t)
            threading.Event().wait(0.02)  # stagger inside the slow save window
        for t in threads:
            t.join()

        assert not concurrent, "two flush() threads entered the batch body at once"

    def test_indexer_save_failure_does_not_skip_remaining_steps(self, tmp_path):
        """A raise from indexer.save() must not abandon the rest of the batch.

        Previously indexer.save() sat outside any handler, so a failure
        skipped graph.save(), the D12 audit trail, and the hybrid-cache
        invalidation — leaving the stores diverged with no record.
        """
        from watchdog.events import FileModifiedEvent
        import intelligence.retrieval.hybrid as hybrid

        handler, indexer, kg = _make_handler(tmp_path, debounce_ms=5000)
        indexer.save.side_effect = FileNotFoundError("ast_index.json.tmp")

        invalidated = {"n": 0}
        original = hybrid.invalidate_hybrid_cache
        hybrid.invalidate_hybrid_cache = lambda: invalidated.__setitem__("n", invalidated["n"] + 1)

        written = {}
        handler._write_last_watcher_reindex = (
            lambda reindexed, removed, error=None: written.update(
                reindexed=reindexed, removed=removed, error=error)
        )

        try:
            f = tmp_path / "auth.py"
            f.write_text("def verify_token(): pass")
            handler.on_modified(FileModifiedEvent(str(f)))
            handler.flush()  # must not raise
        finally:
            hybrid.invalidate_hybrid_cache = original

        kg.save.assert_called_once()
        assert invalidated["n"] == 1, "hybrid cache left holding pre-edit results"
        assert written.get("error"), "partial batch recorded as a clean success"
        assert "auth.py" in written["reindexed"]


# ── D16: watcher liveness must read a file something actually writes ─────────

class TestWatcherAlive:
    def test_reads_heartbeat_not_phantom_pid_file(self, tmp_path, monkeypatch):
        """_watcher_alive() must not depend on .cognirepo/watcher.pid.

        Nothing in the codebase has ever written that path — the daemon
        registers under .cognirepo/watchers/. The old implementation was
        therefore hardwired to False.
        """
        import json as _json
        import interface.cli.daemon as daemon
        from interface.server.mcp_server import _watcher_alive

        watchers = tmp_path / ".cognirepo" / "watchers"
        watchers.mkdir(parents=True)
        monkeypatch.setattr(daemon, "_watchers_dir", lambda: watchers)

        assert _watcher_alive() is False  # nothing running

        import datetime as _dt
        (watchers / "heartbeat").write_text(_json.dumps({
            "pid": os.getpid(),
            "path": str(tmp_path),
            "timestamp": _dt.datetime.utcnow().isoformat() + "Z",
        }))
        assert _watcher_alive() is True, "live heartbeat not detected"

    def test_stale_heartbeat_is_not_alive(self, tmp_path, monkeypatch):
        """A heartbeat older than the staleness threshold must not count as live."""
        import json as _json
        import datetime as _dt
        import interface.cli.daemon as daemon
        from interface.server.mcp_server import _watcher_alive

        watchers = tmp_path / ".cognirepo" / "watchers"
        watchers.mkdir(parents=True)
        monkeypatch.setattr(daemon, "_watchers_dir", lambda: watchers)

        old = _dt.datetime.utcnow() - _dt.timedelta(seconds=daemon._HEARTBEAT_STALE_THRESHOLD + 60)
        (watchers / "heartbeat").write_text(_json.dumps({
            "pid": os.getpid(), "path": str(tmp_path), "timestamp": old.isoformat() + "Z",
        }))

        assert _watcher_alive() is False
