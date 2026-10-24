# pylint: disable=missing-docstring, protected-access, redefined-outer-name, unused-argument, import-outside-toplevel
# SPDX-FileCopyrightText: 2026 Ashlesh T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""tests/test_watch_queue.py — the bounded, coalescing watcher queue and its single consumer (#117)."""
import json
import logging
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import networkx as nx
import pytest
from watchdog.events import FileCreatedEvent, FileDeletedEvent, FileModifiedEvent

from intelligence.indexer import file_watcher
from intelligence.indexer.file_watcher import RepoFileHandler
from intelligence.indexer.watch_queue import WatchQueue, read_status


def wait_until(pred, timeout=10.0, step=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(step)
    return pred()


# ── the queue itself ─────────────────────────────────────────────────────────────────────────────────

class TestWatchQueue:
    def test_fifo_by_first_arrival_and_last_action_wins(self):
        q = WatchQueue(10)
        for name in ("a", "b", "c"):
            assert q.put("reindex", name) == "queued"
        assert q.put("remove", "a") == "coalesced"           # a keeps its place, newest action
        assert q.put("reindex", "b") == "coalesced"
        assert q.take_batch(10) == [("a", "remove"), ("b", "reindex"), ("c", "reindex")]
        assert len(q) == 0

    def test_create_then_delete_collapses_to_a_delete(self):
        q = WatchQueue(10)
        q.put("reindex", "x")
        q.put("remove", "x")
        assert q.snapshot() == {"x": "remove"}

    def test_bounded_and_overflow_is_flagged_once_per_episode(self):
        q = WatchQueue(3)
        results = [q.put("reindex", f"p{i}") for i in range(10)]
        assert results[:3] == ["queued"] * 3 and set(results[3:]) == {"overflow"}
        assert len(q) == 3 and q.overflowed
        assert q.stats["dropped"] == 7 and q.stats["overflows"] == 1
        assert q.take_overflow() is True and q.take_overflow() is False

    def test_a_full_queue_still_coalesces_known_paths(self):
        q = WatchQueue(2)
        q.put("reindex", "a")
        q.put("reindex", "b")
        assert q.put("remove", "a") == "coalesced" and not q.overflowed
        assert q.put("reindex", "c") == "overflow"

    def test_a_new_episode_counts_again(self):
        q = WatchQueue(1)
        q.put("reindex", "a")
        q.put("reindex", "b")
        q.take_overflow()
        q.take_batch(5)
        q.put("reindex", "a")
        q.put("reindex", "z")
        assert q.stats["overflows"] == 2

    def test_take_batch_is_bounded_and_ordered(self):
        q = WatchQueue(100)
        for i in range(25):
            q.put("reindex", f"p{i:02d}")
        first = q.take_batch(10)
        assert [p for p, _ in first] == [f"p{i:02d}" for i in range(10)]
        assert len(q.take_batch(100)) == 15 and q.take_batch(5) == []

    def test_oldest_age_and_describe(self):
        q = WatchQueue(5)
        assert q.oldest_age() == 0.0 and q.describe()["depth"] == 0
        q.put("reindex", "a")
        time.sleep(0.05)
        assert q.oldest_age() >= 0.04
        q.record_batch(3, 12.34)
        d = q.describe()
        assert d["depth"] == 1 and d["max"] == 5 and d["batches"] == 1 and d["files"] == 3
        assert d["last_batch"] == {"files": 3, "ms": 12.3}

    def test_replace_for_code_that_assigns_a_pending_dict(self):
        q = WatchQueue(5)
        q.replace({"a": "reindex", "b": "remove"})
        assert q.snapshot() == {"a": "reindex", "b": "remove"}

    def test_thread_safe_under_contention_and_never_exceeds_the_bound(self):
        q = WatchQueue(200)
        taken, errors = [], []
        stop = threading.Event()

        def produce(n):
            try:
                for i in range(2000):
                    q.put("reindex", f"p{(n * 2000 + i) % 700}")
                    assert len(q) <= 200
            except Exception as exc:  # pylint: disable=broad-except
                errors.append(exc)

        def consume():
            while not stop.is_set() or len(q):
                taken.extend(q.take_batch(50))

        consumer = threading.Thread(target=consume)
        producers = [threading.Thread(target=produce, args=(n,)) for n in range(6)]
        consumer.start()
        for t in producers:
            t.start()
        for t in producers:
            t.join(30)
        stop.set()
        consumer.join(30)
        assert errors == [] and q.stats["max_depth"] <= 200
        assert q.stats["enqueued"] == len(taken)                 # nothing lost between put and take


# ── the handler: one consumer, batches, backpressure ─────────────────────────────────────────────────

class FakeIndexer:
    """Stateful enough for the catch-up scan: index_file stamps indexed_at, remove_file forgets the file."""

    def __init__(self):
        self.index_data = {"files": {}, "reverse_index": {}}
        self.faiss_index = None
        self.order = []
        self.saves = 0
        self._lock = threading.Lock()
        self._build_reverse_index = MagicMock()
        self._resolve_call_stubs = MagicMock()
        self.finish_tombstones = MagicMock()
        self.purge_tombstones = MagicMock(return_value=set())

    def index_file(self, rel, abs_path):
        with self._lock:
            self.order.append(rel)
            rec = {"indexed_at": datetime.now(timezone.utc).isoformat(), "symbols": []}
            self.index_data["files"][rel] = rec
            return rec

    def remove_file(self, rel):
        with self._lock:
            self.order.append(("remove", rel))
            self.index_data["files"].pop(rel, None)
            return set()

    def save(self):
        self.saves += 1


def make_handler(tmp_path, *, debounce_ms=50, queue_max=5000, batch_max=500, max_latency_ms=5000):
    from data.graph.knowledge_graph import KnowledgeGraph
    (tmp_path / ".cognirepo").mkdir(exist_ok=True)
    (tmp_path / ".cognirepo" / "config.json").write_text(json.dumps(
        {"indexing": {"queue_max": queue_max, "batch_max": batch_max, "max_latency_ms": max_latency_ms}}))
    kg = KnowledgeGraph.__new__(KnowledgeGraph)
    kg.G = nx.DiGraph()
    kg.G.graph["complete"] = True
    kg.nodes_for_file = MagicMock(return_value=[])
    kg.remove_file_nodes = MagicMock()
    kg.remove_node_edges = MagicMock()
    kg.save = MagicMock()
    indexer = FakeIndexer()
    handler = RepoFileHandler(repo_root=str(tmp_path), indexer=indexer, graph=kg, behaviour=MagicMock(),
                              session_id="t", debounce_ms=debounce_ms)
    return handler, indexer, kg


def touch(tmp_path, name):
    p = tmp_path / name
    p.write_text("def f():\n    pass\n")
    return str(p)


class TestConfig:
    def test_defaults(self, tmp_path):
        h = RepoFileHandler(str(tmp_path), MagicMock(), MagicMock(), MagicMock(), "t")
        assert (h.debounce_ms, h.batch_max, h.max_latency_ms, h._wq.maxsize) == (500, 500, 5000, 5000)

    def test_read_from_config(self, tmp_path):
        h, _, _ = make_handler(tmp_path, queue_max=7, batch_max=3, max_latency_ms=250)
        assert (h.batch_max, h.max_latency_ms, h._wq.maxsize) == (3, 250, 7)

    @pytest.mark.parametrize("bad", ["lots", None, [1], {"x": 1}])
    def test_garbage_falls_back_to_defaults(self, tmp_path, bad):
        (tmp_path / ".cognirepo").mkdir(exist_ok=True)
        (tmp_path / ".cognirepo" / "config.json").write_text(json.dumps(
            {"indexing": {"queue_max": bad, "batch_max": bad, "max_latency_ms": bad}}))
        h = RepoFileHandler(str(tmp_path), MagicMock(), MagicMock(), MagicMock(), "t", debounce_ms=10)
        assert (h.batch_max, h.max_latency_ms, h._wq.maxsize) == (500, 5000, 5000)


class TestSingleConsumer:
    def test_no_timer_thread_is_ever_started(self, tmp_path, monkeypatch):
        """The old code armed a new threading.Timer (an OS thread) for every event."""
        monkeypatch.setattr(threading, "Timer", lambda *a, **k: pytest.fail("a Timer per event is back"))
        h, ix, _ = make_handler(tmp_path, debounce_ms=100)
        for i in range(300):
            h._queue("reindex", touch(tmp_path, f"f{i % 30}.py"))
        assert wait_until(lambda: len(ix.index_data["files"]) == 30)

    def test_a_burst_of_events_starts_at_most_one_consumer(self, tmp_path):
        started = []
        real_start = threading.Thread.start

        def counting_start(self):
            if self.name == "cognirepo-watch-consumer":
                started.append(self)
            return real_start(self)

        h, ix, _ = make_handler(tmp_path, debounce_ms=300)
        paths = [touch(tmp_path, f"f{i}.py") for i in range(20)]
        threading.Thread.start = counting_start
        try:
            for _ in range(200):
                for p in paths:
                    h._queue("reindex", p)
            consumers = [t for t in threading.enumerate() if t.name == "cognirepo-watch-consumer"]
            assert len(consumers) <= 1 and len(started) == 1
            assert wait_until(lambda: len(ix.index_data["files"]) == 20)
        finally:
            threading.Thread.start = real_start

    def test_the_consumer_exits_when_there_is_nothing_left(self, tmp_path):
        h, ix, _ = make_handler(tmp_path, debounce_ms=30)
        h._queue("reindex", touch(tmp_path, "a.py"))
        assert wait_until(lambda: ix.saves == 1)
        assert wait_until(lambda: h._consumer is None)                 # no idle thread between bursts
        h._queue("reindex", touch(tmp_path, "b.py"))                   # and it restarts for the next one
        assert wait_until(lambda: ix.saves == 2)


class TestBatching:
    def test_flush_drains_in_batches_of_at_most_batch_max(self, tmp_path):
        h, ix, _ = make_handler(tmp_path, debounce_ms=60000, batch_max=500)
        for i in range(1200):
            h._queue("reindex", os.path.join(str(tmp_path), f"f{i}.py"))
        assert len(h._wq) == 1200
        ix.index_file = MagicMock(side_effect=ix.index_file)
        h.flush()
        assert ix.saves == 3                                       # 500 + 500 + 200
        assert [b["files"] for b in [h._wq.stats["last_batch"]]] == [200] and h._wq.stats["batches"] == 3
        assert h._wq.stats["files"] == 1200 and len(h._wq) == 0

    def test_processing_order_is_arrival_order(self, tmp_path):
        h, ix, _ = make_handler(tmp_path, debounce_ms=60000, batch_max=7)
        names = [f"f{i:03d}.py" for i in range(50)]
        for n in names:
            h._queue("reindex", os.path.join(str(tmp_path), n))
        h.flush()
        assert ix.order == names

    def test_same_path_events_collapse_to_one_action(self, tmp_path):
        h, ix, _ = make_handler(tmp_path, debounce_ms=60000)
        p = touch(tmp_path, "x.py")
        h.on_created(FileCreatedEvent(p))
        h.on_modified(FileModifiedEvent(p))
        h.on_deleted(FileDeletedEvent(p))
        assert h._pending == {p: "remove"}
        h.flush()
        assert ix.order == [("remove", "x.py")]

    def test_assigning_pending_still_works(self, tmp_path):
        h, ix, _ = make_handler(tmp_path, debounce_ms=60000)
        h._pending = {os.path.join(str(tmp_path), "z.py"): "reindex"}
        h.flush()
        assert ix.order == ["z.py"]


class TestTiming:
    def test_events_inside_the_window_wait_then_flush_once_quiet(self, tmp_path):
        h, ix, _ = make_handler(tmp_path, debounce_ms=300, max_latency_ms=60000)
        p = touch(tmp_path, "a.py")
        t0 = time.time()
        while time.time() - t0 < 0.6:                              # keep touching for 0.6 s (> the window)
            h._queue("reindex", p)
            time.sleep(0.05)
            assert ix.saves == 0, "flushed while events were still arriving"
        assert wait_until(lambda: ix.saves == 1, 5)
        assert time.time() - t0 >= 0.85                            # last event + the 300 ms quiet period

    def test_constant_churn_still_flushes_within_max_latency(self, tmp_path):
        h, ix, _ = make_handler(tmp_path, debounce_ms=2000, max_latency_ms=400)
        t0 = time.time()
        first_flush = None
        for i in range(40):                                        # a new path every 50 ms for 2 s
            h._queue("reindex", touch(tmp_path, f"f{i}.py"))
            time.sleep(0.05)
            if first_flush is None and ix.saves:
                first_flush = time.time() - t0
        assert first_flush is not None and first_flush < 1.3       # without max_latency it would wait ~4 s
        assert wait_until(lambda: len(ix.index_data["files"]) == 40, 10)

    def test_debounce_zero_is_still_synchronous(self, tmp_path):
        h, ix, _ = make_handler(tmp_path, debounce_ms=0)
        h._queue("reindex", touch(tmp_path, "now.py"))
        assert ix.order == ["now.py"] and h._consumer is None


class TestBackpressure:
    def _git_repo(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    def test_memory_stays_bounded_during_a_flood(self, tmp_path):
        h, ix, _ = make_handler(tmp_path, debounce_ms=60000, queue_max=100)
        for i in range(20000):
            h._queue("reindex", os.path.join(str(tmp_path), f"f{i}.py"))
            assert len(h._wq) <= 100
        assert h._wq.stats["max_depth"] == 100 and h._wq.stats["dropped"] == 19900
        h._wq.take_overflow()
        h._wq.take_batch(100)

    def test_overflow_is_logged_once_per_episode_not_per_event(self, tmp_path, caplog):
        h, _, _ = make_handler(tmp_path, debounce_ms=60000, queue_max=5)
        with caplog.at_level(logging.WARNING, logger=file_watcher.log.name):
            for i in range(2000):
                h._queue("reindex", os.path.join(str(tmp_path), f"f{i}.py"))
        assert len([r for r in caplog.records if "queue full" in r.getMessage()]) == 1

    def test_overflow_converges_on_the_filesystem_via_catch_up(self, tmp_path):
        """More new files than the queue holds: nothing is lost, every file ends up indexed exactly once."""
        self._git_repo(tmp_path)
        h, ix, _ = make_handler(tmp_path, debounce_ms=50, queue_max=20, batch_max=10)
        paths = [touch(tmp_path, f"f{i:03d}.py") for i in range(150)]
        for p in paths:
            h.on_created(FileCreatedEvent(p))
        assert wait_until(lambda: len(ix.index_data["files"]) == 150, 20)
        assert h._wq.stats["overflows"] >= 1 and h._wq.stats["max_depth"] <= 20
        assert sorted(ix.order) == sorted(f"f{i:03d}.py" for i in range(150))     # each exactly once, none missed

    def test_deletions_dropped_by_overflow_are_reconciled_too(self, tmp_path):
        self._git_repo(tmp_path)
        h, ix, _ = make_handler(tmp_path, debounce_ms=50, queue_max=5, batch_max=5)
        paths = [touch(tmp_path, f"d{i:02d}.py") for i in range(40)]
        for p in paths:                                            # index them all first (quiet filesystem)
            h._queue("reindex", p)
        h.flush()
        assert len(ix.index_data["files"]) == 40
        for p in paths:
            os.remove(p)
        for p in paths:
            h.on_deleted(FileDeletedEvent(p))
        assert wait_until(lambda: ix.index_data["files"] == {}, 20)
        assert h._wq.stats["overflows"] >= 1

    def test_without_git_an_overflow_is_reported_and_does_not_loop(self, tmp_path, caplog):
        h, ix, _ = make_handler(tmp_path, debounce_ms=60000, queue_max=3, batch_max=3)   # no `git init`
        for i in range(10):
            h._queue("reindex", touch(tmp_path, f"n{i}.py"))
        started = time.time()
        with caplog.at_level(logging.WARNING, logger=file_watcher.log.name):
            h.flush()
        assert time.time() - started < 10
        assert any("catch-up scan found nothing" in r.getMessage() for r in caplog.records)

    def test_reconciliation_gives_up_after_a_bounded_number_of_passes(self, tmp_path, monkeypatch, caplog):
        h, _, _ = make_handler(tmp_path, debounce_ms=60000, queue_max=2, batch_max=2)
        calls = []

        def hostile_catch_up(handler):                             # every pass overflows the queue again
            calls.append(1)
            for i in range(50):
                handler._queue("reindex", os.path.join(str(tmp_path), f"c{len(calls)}_{i}.py"))
            return 50

        monkeypatch.setattr(file_watcher, "catch_up", hostile_catch_up)
        for i in range(10):
            h._queue("reindex", os.path.join(str(tmp_path), f"s{i}.py"))
        with caplog.at_level(logging.WARNING, logger=file_watcher.log.name):
            h.flush()
        assert len(calls) == file_watcher._MAX_CATCHUP_PASSES
        assert any("stopping reconciliation" in r.getMessage() for r in caplog.records)


class TestObservability:
    def test_status_file_after_a_flush(self, tmp_path):
        (tmp_path / ".cognirepo").mkdir(exist_ok=True)
        h, ix, _ = make_handler(tmp_path, debounce_ms=60000, batch_max=4)
        for i in range(10):
            h._queue("reindex", os.path.join(str(tmp_path), f"f{i}.py"))
        h.flush()
        doc = read_status(str(tmp_path / ".cognirepo"))
        assert doc["depth"] == 0 and doc["max"] == 5000 and doc["batches"] == 3 and doc["files"] == 10
        assert doc["pid"] == os.getpid() and doc["batch_max"] == 4 and doc["last_batch"]["files"] == 2
        assert doc["enqueued"] == 10 and doc["overflows"] == 0
        assert not [f for f in os.listdir(tmp_path / ".cognirepo" / "index") if ".tmp" in f]

    def test_status_of_a_dead_watcher_is_not_reported(self, tmp_path):
        d = tmp_path / ".cognirepo" / "index"
        d.mkdir(parents=True, exist_ok=True)
        dead = subprocess.Popen(["true"])
        dead.wait()
        (d / "watch_queue.json").write_text(json.dumps({"depth": 9, "pid": dead.pid}))
        assert read_status(str(tmp_path / ".cognirepo")) is None
        (d / "watch_queue.json").write_text("{not json")
        assert read_status(str(tmp_path / ".cognirepo")) is None
        assert read_status(str(tmp_path / "nowhere")) is None

    def test_exposed_through_the_control_api_status(self, tmp_path, monkeypatch):
        from interface.ui import status
        d = tmp_path / ".cognirepo" / "index"
        d.mkdir(parents=True, exist_ok=True)
        (d / "watch_queue.json").write_text(json.dumps({"depth": 3, "max": 5000, "pid": os.getpid(), "overflows": 1}))
        monkeypatch.setattr(status, "_store_dir", lambda _r: str(tmp_path / ".cognirepo"))
        wq = status.indexer_status(str(tmp_path))["watch_queue"]
        assert wq["depth"] == 3 and wq["overflows"] == 1

    def test_prometheus_gauges(self, tmp_path):
        pytest.importorskip("prometheus_client")
        from interface.ui.store_metrics import StoreCollector
        d = tmp_path / ".cognirepo" / "index"
        d.mkdir(parents=True, exist_ok=True)
        (d / "watch_queue.json").write_text(json.dumps(
            {"depth": 7, "max": 5000, "oldest_age_s": 1.5, "overflows": 2, "dropped": 40, "batches": 9, "pid": os.getpid()}))
        fams = {f.name: f for f in StoreCollector(str(tmp_path / ".cognirepo"), "r", str(tmp_path)).collect()}
        assert fams["cognirepo_watcher_queue_depth"].samples[0].value == 7
        assert fams["cognirepo_watcher_queue_oldest_age_seconds"].samples[0].value == 1.5
        assert fams["cognirepo_watcher_queue_overflows"].samples[0].value == 2     # counters are exposed with _total on scrape
        assert fams["cognirepo_watcher_queue_capacity"].samples[0].value == 5000


class TestShutdown:
    def test_flush_and_stop_drains_every_batch(self, tmp_path):
        from interface.cli.main import _flush_and_stop_observer
        h, ix, _ = make_handler(tmp_path, debounce_ms=60000, batch_max=5)
        for i in range(23):
            h._queue("reindex", os.path.join(str(tmp_path), f"f{i}.py"))
        obs = MagicMock()
        obs._cognirepo_handler = h
        _flush_and_stop_observer(obs)
        assert ix.saves == 5 and len(ix.index_data["files"]) == 23 and len(h._wq) == 0
        obs.stop.assert_called_once()
