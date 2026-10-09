# SPDX-FileCopyrightText: 2026 Ashlesh T
# SPDX-License-Identifier: MIT
"""Lock hygiene (COGNIREPO-141): bounded waits, structured errors, short holds, lock order.

Before: a lock timeout surfaced as a raw ``filelock.Timeout`` traceback (and on the CLI a crash);
the org-graph lock had NO timeout so one hung holder blocked every repo; ``git rev-parse`` and the
keyring ran while holding the store lock; ``last_context.json`` (in $HOME) was guarded by a
repo-local lock and its read-modify-write read the old file outside the lock; nothing enforced the
"never nest two different store locks" rule.
"""
import json
import logging
import os
import threading
import time

import pytest

from core.config import lock as lockmod
from core.config.lock import LockOrderError, StoreBusy, store_lock


def _hold(path_lock, started: threading.Event, release: threading.Event):
    with path_lock:
        started.set()
        release.wait(30)


class TestStoreBusy:
    def test_a_timeout_is_a_structured_retryable_error(self, isolated_cognirepo):
        from filelock import Timeout
        started, release = threading.Event(), threading.Event()
        t = threading.Thread(target=_hold, args=(store_lock(), started, release))
        t.start()
        assert started.wait(10)
        try:
            with pytest.raises(StoreBusy) as exc:
                with store_lock(timeout=0.2):
                    pass
        finally:
            release.set()
            t.join(10)
        e = exc.value
        assert isinstance(e, Timeout)                                   # old `except Timeout` code still works
        assert e.timeout == 0.2 and e.lock_path.endswith("cognirepo.lock")
        assert "busy" in str(e) and "retry" in str(e) and "cognirepo.lock" in str(e)

    def test_a_failed_acquire_leaves_nothing_registered(self, isolated_cognirepo):
        started, release = threading.Event(), threading.Event()
        t = threading.Thread(target=_hold, args=(store_lock(), started, release))
        t.start()
        assert started.wait(10)
        with pytest.raises(StoreBusy):
            store_lock(timeout=0.1).acquire()
        release.set()
        t.join(10)
        with store_lock(timeout=2):                                     # and it is takeable afterwards
            pass


class TestHoldTime:
    def test_a_long_hold_is_logged_with_its_duration(self, isolated_cognirepo, monkeypatch, caplog):
        monkeypatch.setenv("COGNIREPO_LOCK_HOLD_WARN_SECS", "0.05")
        with caplog.at_level(logging.WARNING, logger=lockmod.__name__):
            with store_lock():
                time.sleep(0.2)
        assert any("was held for" in r.getMessage() for r in caplog.records)

    def test_a_short_hold_is_silent(self, isolated_cognirepo, caplog):
        with caplog.at_level(logging.WARNING, logger=lockmod.__name__):
            with store_lock():
                pass
        assert not caplog.records


class TestLockOrder:
    def test_reentering_the_same_lock_is_fine(self, isolated_cognirepo):
        with store_lock():
            with store_lock():
                pass

    def test_nesting_two_different_locks_raises_in_strict_mode(self, isolated_cognirepo, tmp_path):
        with store_lock():
            with pytest.raises(LockOrderError):
                with store_lock(lock_path=str(tmp_path / "other.lock")):
                    pass

    def test_outside_strict_mode_it_warns_once(self, isolated_cognirepo, tmp_path, monkeypatch, caplog):
        monkeypatch.delenv("COGNIREPO_LOCK_STRICT")
        lockmod._NESTING_SEEN.clear()
        other = str(tmp_path / "other2.lock")
        with caplog.at_level(logging.WARNING, logger=lockmod.__name__):
            for _ in range(3):
                with store_lock():
                    with store_lock(lock_path=other):
                        pass
        msgs = [r.getMessage() for r in caplog.records if "nested store locks" in r.getMessage()]
        assert len(msgs) == 1

    def test_sequential_different_locks_are_fine(self, isolated_cognirepo, tmp_path):
        with store_lock():
            pass
        with store_lock(lock_path=str(tmp_path / "other3.lock")):
            pass


def _lock_is_free_from_another_thread() -> bool:
    """True if the repo store lock can be taken right now by a different thread."""
    result = []

    def probe():
        try:
            with store_lock(timeout=0):
                result.append(True)
        except StoreBusy:
            result.append(False)

    t = threading.Thread(target=probe)
    t.start()
    t.join(10)
    return bool(result and result[0])


class TestWorkOutsideTheLock:
    def test_git_rev_parse_runs_without_the_store_lock(self, isolated_cognirepo, tmp_path, monkeypatch, caplog):
        import intelligence.indexer.ast_indexer as ai
        from data.graph.knowledge_graph import KnowledgeGraph
        (tmp_path / "a.py").write_text("def f():\n    return 1\n")
        ix = ai.ASTIndexer(graph=KnowledgeGraph())
        ix._embed_enabled = False
        ix.index_file("a.py", str(tmp_path / "a.py"))
        seen = {}

        def slow_git_head(_repo=None):
            seen["free"] = _lock_is_free_from_another_thread()
            time.sleep(1.2)                                    # a slow `git` on a big repo / network fs
            return "deadbeef"

        monkeypatch.setattr(ai, "_git_head", slow_git_head)
        monkeypatch.setenv("COGNIREPO_LOCK_HOLD_WARN_SECS", "0.8")
        with caplog.at_level(logging.WARNING, logger=lockmod.__name__):
            ix.save()
        assert seen["free"] is True, "git rev-parse ran while the store lock was held"
        assert not [r for r in caplog.records if "was held for" in r.getMessage()], \
            "the lock was held across the slow git call"
        manifest = json.load(open(ai._manifest_file(), encoding="utf-8"))
        assert manifest["git_commit"] == "deadbeef"            # and the manifest still records it

    def test_keyring_lookup_runs_without_the_store_lock(self, isolated_cognirepo, monkeypatch):
        pytest.importorskip("cryptography")
        pytest.importorskip("keyring")
        from unittest import mock
        import core.security.encryption as enc
        from data.graph.knowledge_graph import KnowledgeGraph
        with open(".cognirepo/config.json", "w", encoding="utf-8") as f:
            json.dump({"project_id": "lock-enc", "storage": {"encrypt": True}}, f)
        store: dict = {}
        real = enc.get_or_create_key
        seen = []

        def spy(project_id):
            seen.append(_lock_is_free_from_another_thread())
            return real(project_id)

        with mock.patch("keyring.get_password", side_effect=lambda s, p: store.get(p)), \
             mock.patch("keyring.set_password", side_effect=lambda s, p, v: store.__setitem__(p, v)):
            monkeypatch.setattr(enc, "get_or_create_key", spy)
            kg = KnowledgeGraph()
            kg.add_node("n1", "FILE")
            kg.save()
        assert seen and all(seen), "the keychain was queried while the store lock was held"


class TestOrgGraphLock:
    def test_the_wait_is_bounded_and_reports_store_busy(self, isolated_cognirepo, tmp_path, monkeypatch):
        import data.graph.org_graph as og
        monkeypatch.setenv("COGNIREPO_ORG_GRAPH", str(tmp_path / "org" / "g.pkl"))
        monkeypatch.setattr(og, "_ORG_LOCK_TIMEOUT", 0.2)
        started, release = threading.Event(), threading.Event()
        t = threading.Thread(target=_hold, args=(og._org_lock(), started, release))   # the hung holder
        t.start()
        assert started.wait(10)
        t0 = time.time()
        try:
            with pytest.raises(StoreBusy):
                og.OrgGraph().save()
        finally:
            release.set()
            t.join(10)
        assert time.time() - t0 < 5, "must give up after the timeout, not wait forever"

    def test_a_busy_load_is_not_mistaken_for_an_empty_graph(self, isolated_cognirepo, tmp_path, monkeypatch):
        """Load used to turn ANY failure into 'start fresh' - a busy lock would have meant an empty org."""
        import data.graph.org_graph as og
        graph = tmp_path / "org2" / "g.pkl"
        monkeypatch.setenv("COGNIREPO_ORG_GRAPH", str(graph))
        first = og.OrgGraph()
        first.add_repo(str(tmp_path / "repoA"))
        first.save()
        monkeypatch.setattr(og, "_ORG_LOCK_TIMEOUT", 0.2)
        started, release = threading.Event(), threading.Event()
        t = threading.Thread(target=_hold, args=(og._org_lock(), started, release))
        t.start()
        assert started.wait(10)
        try:
            with pytest.raises(StoreBusy):
                og.OrgGraph()                       # constructor loads
        finally:
            release.set()
            t.join(10)
        assert og.OrgGraph().list_repos()           # and once free, the repo is still there

    def test_lock_follows_the_graph_override_and_creates_its_directory(self, isolated_cognirepo, tmp_path, monkeypatch):
        import data.graph.org_graph as og
        monkeypatch.setenv("COGNIREPO_ORG_GRAPH", str(tmp_path / "newdir" / "g.pkl"))
        assert og._org_lock_path() == str(tmp_path / "newdir" / "g.pkl") + ".lock"
        with og._org_lock():
            assert os.path.isdir(tmp_path / "newdir")

    def test_default_graph_keeps_the_historical_lock_name(self, isolated_cognirepo, monkeypatch):
        import data.graph.org_graph as og
        monkeypatch.delenv("COGNIREPO_ORG_GRAPH", raising=False)
        assert os.path.basename(og._org_lock_path()) == "org_graph.lock"

    def test_the_lock_is_reentrant(self, isolated_cognirepo, tmp_path, monkeypatch):
        import data.graph.org_graph as og
        monkeypatch.setenv("COGNIREPO_ORG_GRAPH", str(tmp_path / "g2.pkl"))
        with og._org_lock():
            with og._org_lock():
                pass


class TestLastContext:
    def _setup(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path / "home") if p == "~" else p)
        with open(".cognirepo/config.json", "w", encoding="utf-8") as f:
            json.dump({"project_id": "lc", "project_name": "lcproj", "autosave_context": True}, f)
        return str(tmp_path / "home" / ".cognirepo" / "lcproj")

    def test_it_has_its_own_lock_next_to_the_file(self, isolated_cognirepo, tmp_path, monkeypatch):
        from interface.tools import context_pack as cp
        save_dir = self._setup(tmp_path, monkeypatch)
        os.makedirs(save_dir)
        lk = cp._last_context_lock(save_dir)
        assert lk._path == os.path.abspath(os.path.join(save_dir, ".last_context.lock"))   # pylint: disable=protected-access
        started, release = threading.Event(), threading.Event()
        t = threading.Thread(target=_hold, args=(cp._last_context_lock(save_dir), started, release))
        t.start()
        assert started.wait(10)
        try:
            assert _lock_is_free_from_another_thread()            # the repo store lock is NOT involved
        finally:
            release.set()
            t.join(10)

    def test_read_modify_write_reads_inside_the_lock(self, isolated_cognirepo, tmp_path, monkeypatch):
        """A concurrent writer's sections must survive: the old file used to be read BEFORE the lock."""
        from interface.tools import context_pack as cp
        from core.config.atomic import atomic_json_dump
        save_dir = self._setup(tmp_path, monkeypatch)
        os.makedirs(save_dir)
        ctx = os.path.join(save_dir, "last_context.json")
        started, release = threading.Event(), threading.Event()
        holder = threading.Thread(target=_hold, args=(cp._last_context_lock(save_dir), started, release))
        holder.start()
        assert started.wait(10)
        worker = threading.Thread(target=cp.save_query_context, args=("how does x work", "search"))
        worker.start()
        time.sleep(0.4)                                            # worker has started and is waiting for the lock
        atomic_json_dump(ctx, {"agent": "cognirepo", "repo": "lcproj", "sections": [{"file": "a.py"}]}, fsync=False)
        release.set()                                              # concurrent writer finished
        worker.join(10)
        holder.join(10)
        data = json.load(open(ctx, encoding="utf-8"))
        assert data["query"] == "how does x work"
        assert data["sections"] == [{"file": "a.py"}], "the concurrent writer's sections were lost"

    def test_it_never_stalls_a_tool_call(self, isolated_cognirepo, tmp_path, monkeypatch):
        from interface.tools import context_pack as cp
        save_dir = self._setup(tmp_path, monkeypatch)
        os.makedirs(save_dir)
        monkeypatch.setattr(cp, "_LAST_CONTEXT_LOCK_TIMEOUT", 0.2)
        started, release = threading.Event(), threading.Event()
        t = threading.Thread(target=_hold, args=(cp._last_context_lock(save_dir), started, release))
        t.start()
        assert started.wait(10)
        t0 = time.time()
        try:
            cp.save_query_context("q", "search")                  # best-effort: must return, not raise
        finally:
            release.set()
            t.join(10)
        assert time.time() - t0 < 5


class TestSurfaces:
    def test_mcp_tools_return_a_structured_busy_result(self, isolated_cognirepo):
        from interface.server import mcp_server

        def busy():
            raise StoreBusy("/x/cognirepo.lock", 15.0)

        res = mcp_server._traced("store_memory", busy)             # pylint: disable=protected-access
        assert res["busy"] is True and res["retryable"] is True and res["tool"] == "store_memory"
        assert "busy" in res["error"] and "retry" in res["error"]

    def test_a_busy_store_memory_is_not_recorded_as_stored(self, isolated_cognirepo, monkeypatch):
        from interface.server import mcp_server
        recorded = []
        monkeypatch.setattr(mcp_server, "_store_memory",
                            lambda *_a: (_ for _ in ()).throw(StoreBusy("/x/cognirepo.lock", 15.0)))
        monkeypatch.setattr(mcp_server, "intercept_after_store", lambda *a, **k: recorded.append(a))
        res = mcp_server.store_memory("remember this")
        assert res.get("busy") is True and recorded == []

    def test_the_cli_exits_75_with_a_message_not_a_traceback(self, isolated_cognirepo, monkeypatch, capsys):
        import interface.cli.main as cli
        monkeypatch.setattr(cli, "_main", lambda: (_ for _ in ()).throw(StoreBusy("/x/cognirepo.lock", 15.0)))
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 75
        err = capsys.readouterr().err
        assert "busy" in err and "Traceback" not in err


# ── review of #183: the same class of bug in the locks that did not go through store_lock ────────────

def _held_in_thread(lock):
    started, release = threading.Event(), threading.Event()
    t = threading.Thread(target=_hold, args=(lock, started, release))
    t.start()
    assert started.wait(10)
    return t, release


class TestBehaviourLock:
    """BehaviourTracker had its own raw FileLock: a timeout was a bare filelock.Timeout traceback."""

    def test_a_busy_behaviour_file_is_store_busy_not_a_raw_timeout(self, isolated_cognirepo, monkeypatch):
        import data.graph.behaviour_tracker as bt
        from data.graph.knowledge_graph import KnowledgeGraph
        monkeypatch.setattr(bt, "_BEHAVIOUR_LOCK_TIMEOUT", 0.2)
        tracker = bt.BehaviourTracker(graph=KnowledgeGraph())
        tracker.record_query("q1", "hello there world", ["s1"], [1])
        t, release = _held_in_thread(bt._behaviour_lock())            # pylint: disable=protected-access
        try:
            with pytest.raises(StoreBusy):
                tracker.save()
        finally:
            release.set()
            t.join(10)
        tracker.save()                                                 # and it works once the holder is gone
        assert "q1" in json.load(open(bt._behaviour_file(), encoding="utf-8"))["query_history"]   # pylint: disable=protected-access

    def test_the_behaviour_lock_is_reentrant(self, isolated_cognirepo):
        import data.graph.behaviour_tracker as bt
        with bt._behaviour_lock():                                     # pylint: disable=protected-access
            with bt._behaviour_lock():                                 # pylint: disable=protected-access
                pass


class TestTier2QueueLocks:
    """A busy queue lock used to read as 'queue empty' / '0 files' / was logged and dropped."""

    def _queue(self, tmp_path):
        from core.config.paths import pending_tier2_path
        q = pending_tier2_path()
        os.makedirs(os.path.dirname(q), exist_ok=True)
        with open(q, "w", encoding="utf-8") as f:
            json.dump({"repo_root": str(tmp_path), "files": [{"rel_path": "a.py"}], "embed_pending": False}, f)
        return q

    def test_a_busy_read_is_not_an_empty_queue(self, isolated_cognirepo, tmp_path, monkeypatch):
        from intelligence.indexer import on_demand
        q = self._queue(tmp_path)
        monkeypatch.setattr(on_demand, "_QUEUE_READ_WAIT", 0.2)
        t, release = _held_in_thread(store_lock(timeout=5, lock_path=q + ".lock"))
        try:
            with pytest.raises(StoreBusy):
                on_demand._load_queue(q)                               # pylint: disable=protected-access
        finally:
            release.set()
            t.join(10)
        assert on_demand._load_queue(q)["files"] == [{"rel_path": "a.py"}]   # pylint: disable=protected-access

    def test_expand_on_access_reports_busy_instead_of_a_false_miss(self, isolated_cognirepo, tmp_path, monkeypatch):
        from intelligence.indexer import on_demand
        q = self._queue(tmp_path)
        monkeypatch.setattr(on_demand, "_QUEUE_READ_WAIT", 0.2)
        t, release = _held_in_thread(store_lock(timeout=5, lock_path=q + ".lock"))
        try:
            with pytest.raises(StoreBusy):
                on_demand.expand_on_access("a.py", str(tmp_path), object())
        finally:
            release.set()
            t.join(10)

    def test_an_unreadable_queue_file_is_still_just_empty(self, isolated_cognirepo, tmp_path):
        from intelligence.indexer import on_demand
        q = self._queue(tmp_path)
        open(q, "w", encoding="utf-8").write("{ not json")
        assert on_demand._load_queue(q) == {}                          # pylint: disable=protected-access

    def test_trimming_the_queue_is_best_effort(self, isolated_cognirepo, tmp_path, monkeypatch, caplog):
        from intelligence.indexer import on_demand
        q = self._queue(tmp_path)
        monkeypatch.setattr(on_demand, "_QUEUE_WRITE_WAIT", 0.2)
        t, release = _held_in_thread(store_lock(timeout=5, lock_path=q + ".lock"))
        try:
            with caplog.at_level(logging.WARNING):
                on_demand._save_queue(q, {"files": []})                # must not raise: idempotent bookkeeping  # pylint: disable=protected-access
        finally:
            release.set()
            t.join(10)
        assert any("failed to update queue" in r.getMessage() for r in caplog.records)

    def test_losing_the_tier2_queue_write_is_loud(self, isolated_cognirepo, tmp_path, monkeypatch):
        """A lost queue means the Tier-2 files are never indexed - it used to be a logged warning."""
        import intelligence.indexer.ast_indexer as ai
        from core.config.paths import pending_tier2_path
        from data.graph.knowledge_graph import KnowledgeGraph
        monkeypatch.setattr(ai, "_QUEUE_LOCK_WAIT", 0.2)
        qpath = pending_tier2_path()
        os.makedirs(os.path.dirname(qpath), exist_ok=True)
        ix = ai.ASTIndexer(graph=KnowledgeGraph())
        t, release = _held_in_thread(store_lock(timeout=5, lock_path=qpath + ".lock"))
        try:
            with pytest.raises(StoreBusy):
                ix._write_pending_tier2(str(tmp_path), [{"rel_path": "a.py"}])   # pylint: disable=protected-access
        finally:
            release.set()
            t.join(10)
        ix._write_pending_tier2(str(tmp_path), [{"rel_path": "a.py"}])           # pylint: disable=protected-access
        assert json.load(open(qpath, encoding="utf-8"))["files"] == [{"rel_path": "a.py"}]


class TestAnyLockTimeoutIsReportedAsBusy:
    """Surfaces catch the filelock.Timeout base class, so a lock that is not yet on store_lock (or a
    future raw FileLock) still gets the structured result instead of a traceback."""

    def test_mcp_maps_a_raw_filelock_timeout(self, isolated_cognirepo):
        from filelock import Timeout
        from interface.server import mcp_server

        def raw():
            raise Timeout("/x/some.lock")

        res = mcp_server._traced("lookup_symbol", raw)                 # pylint: disable=protected-access
        assert res["busy"] is True and res["retryable"] is True
        assert "busy" in res["error"] and "/x/some.lock" in res["error"]

    def test_cli_maps_a_raw_filelock_timeout_to_exit_75(self, isolated_cognirepo, monkeypatch, capsys):
        from filelock import Timeout
        import interface.cli.main as cli
        monkeypatch.setattr(cli, "_main", lambda: (_ for _ in ()).throw(Timeout("/x/some.lock")))
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 75
        err = capsys.readouterr().err
        assert "busy" in err and "/x/some.lock" in err and "Traceback" not in err

    def test_no_raw_filelock_is_left_in_the_store_code(self):
        """Guard: every store/queue lock goes through store_lock() (re-entrant, StoreBusy, order-checked)."""
        import pathlib
        import re
        root = pathlib.Path(__file__).resolve().parents[1]
        allowed = {"core/config/lock.py", "data/graph/journal.py"}      # store_lock itself; the lease (JournalBusy)
        offenders = []
        for sub in ("core", "data", "intelligence", "interface"):
            for p in (root / sub).rglob("*.py"):
                rel = p.relative_to(root).as_posix()
                if rel in allowed:
                    continue
                if re.search(r"\bFileLock\(", p.read_text(encoding="utf-8")):
                    offenders.append(rel)
        assert not offenders, f"raw FileLock( outside store_lock: {offenders} - use core.config.lock.store_lock"
