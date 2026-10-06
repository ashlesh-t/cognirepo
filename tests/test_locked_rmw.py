# pylint: disable=missing-docstring, import-outside-toplevel, too-few-public-methods, protected-access
# pylint: disable=redefined-outer-name, unused-argument, duplicate-code
# SPDX-FileCopyrightText: 2026 Ashlesh T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_locked_rmw.py — COGNIREPO-136 (and the re-entrancy part of #141).

Every read-modify-write of a shared store runs under the cross-process lock and reloads inside
it, so concurrent processes neither lose updates nor mint duplicate ids. The stress tests here
use real OS processes.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import threading

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_workers(tmp_path, body: str, n: int = 8, timeout: int = 180) -> None:
    """Run ``n`` copies of ``body`` as separate processes against tmp_path/.cognirepo."""
    preamble = (
        "import sys, os\n"
        f"sys.path.insert(0, {_REPO!r})\n"
        "WORKER = int(sys.argv[1])\n"
    )
    env = dict(os.environ, COGNIREPO_DIR=str(tmp_path / ".cognirepo"))
    procs = [
        subprocess.Popen([sys.executable, "-c", preamble + body, str(i)], cwd=tmp_path, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for i in range(n)
    ]
    failures = []
    for i, p in enumerate(procs):
        _out, err = p.communicate(timeout=timeout)
        if p.returncode != 0:
            failures.append(f"worker {i}: {err[-600:]}")
    assert not failures, "\n".join(failures)


# ── the lock itself ───────────────────────────────────────────────────────────

class TestReentrantLock:
    def test_nested_acquire_by_the_same_thread_does_not_deadlock(self, tmp_path):
        import time
        from core.config.lock import store_lock
        lp = str(tmp_path / "x.lock")
        t0 = time.time()
        with store_lock(timeout=3, lock_path=lp):
            with store_lock(timeout=3, lock_path=lp):
                with store_lock(timeout=3, lock_path=lp):
                    pass
        assert time.time() - t0 < 2, "nested store_lock used to block on its own fd"

    def test_another_thread_is_still_excluded_until_the_outermost_exit(self, tmp_path):
        from filelock import Timeout
        from core.config.lock import store_lock
        lp = str(tmp_path / "x.lock")
        results: list[str] = []

        def contender():
            try:
                with store_lock(timeout=0.2, lock_path=lp):
                    results.append("acquired")
            except Timeout:
                results.append("timeout")

        with store_lock(lock_path=lp):
            with store_lock(lock_path=lp):
                pass                                  # inner exit must NOT release the OS lock
                t = threading.Thread(target=contender)
                t.start()
                t.join()
        assert results == ["timeout"]
        t = threading.Thread(target=contender)
        t.start()
        t.join()
        assert results == ["timeout", "acquired"]

    def test_lock_is_released_when_the_body_raises(self, tmp_path):
        from core.config.lock import store_lock
        lp = str(tmp_path / "x.lock")
        with pytest.raises(RuntimeError):
            with store_lock(lock_path=lp):
                raise RuntimeError("boom")
        with store_lock(timeout=0.5, lock_path=lp):   # free again, and the depth map is clean
            pass

    def test_timeout_surfaces_as_filelock_timeout_and_registers_nothing(self, tmp_path):
        from filelock import Timeout
        from core.config.lock import store_lock, _held
        lp = str(tmp_path / "x.lock")
        held, release = threading.Event(), threading.Event()

        def holder():
            with store_lock(lock_path=lp):
                held.set()
                release.wait(10)
        t = threading.Thread(target=holder)
        t.start()
        assert held.wait(10)
        try:
            with pytest.raises(Timeout):
                with store_lock(timeout=0.1, lock_path=lp):
                    pass
            assert os.path.abspath(lp) not in _held()
        finally:
            release.set()
            t.join()


# ── multi-process stress (the issue's acceptance tests) ───────────────────────

class TestEpisodicStress:
    def test_8_processes_x_50_log_events_yield_400_unique_ids(self, isolated_cognirepo):
        body = (
            "from data.memory.episodic_memory import log_event\n"
            "for i in range(50):\n"
            "    log_event(f'w{WORKER}-e{i}', {'w': WORKER})\n"
        )
        _run_workers(isolated_cognirepo, body, n=8)
        from data.memory.episodic_memory import get_history
        events = get_history(limit=10_000)
        ids = [e["id"] for e in events]
        assert len(events) == 400, f"lost {400 - len(events)} events"
        assert len(set(ids)) == 400, "duplicate ids minted"
        assert {e["event"] for e in events} == {f"w{w}-e{i}" for w in range(8) for i in range(50)}

    def test_mark_stale_running_beside_writers_loses_no_events(self, isolated_cognirepo):
        writers = (
            "from data.memory.episodic_memory import log_event\n"
            "for i in range(40):\n"
            "    log_event(f'touch app.py w{WORKER}-{i}', {})\n"
        )
        stale = (
            "from data.memory.episodic_memory import mark_stale\n"
            "for _ in range(40):\n"
            "    mark_stale('app.py')\n"
        )
        env = dict(os.environ, COGNIREPO_DIR=str(isolated_cognirepo / ".cognirepo"))
        pre = f"import sys\nsys.path.insert(0, {_REPO!r})\nWORKER = int(sys.argv[1])\n"
        procs = [subprocess.Popen([sys.executable, "-c", pre + (writers if i < 5 else stale), str(i)],
                                  cwd=isolated_cognirepo, env=env, stderr=subprocess.PIPE, text=True)
                 for i in range(6)]
        for p in procs:
            _, err = p.communicate(timeout=180)
            assert p.returncode == 0, err[-500:]
        from data.memory.episodic_memory import get_history
        events = get_history(limit=10_000)
        assert len(events) == 5 * 40
        assert len({e["id"] for e in events}) == 200


class TestLearningsStress:
    def test_distinct_learnings_from_8_processes_are_all_kept(self, isolated_cognirepo):
        root = isolated_cognirepo / "learn"
        body = (
            "from pathlib import Path\n"
            "from data.memory.learning_store import _LearningBackend\n"
            f"s = _LearningBackend(Path({str(root)!r}))\n"
            "for i in range(25):\n"
            "    s.store('correction', f'learning w{WORKER} number {i}', {}, 'repo')\n"
        )
        _run_workers(isolated_cognirepo, body, n=8)
        records = json.loads((root / "learnings.json").read_text())
        assert len(records) == 200, f"lost {200 - len(records)} learnings"
        assert len({r["id"] for r in records}) == 200

    def test_the_same_text_stored_by_8_processes_is_stored_once(self, isolated_cognirepo):
        root = isolated_cognirepo / "learn"
        body = (
            "from pathlib import Path\n"
            "from data.memory.learning_store import _LearningBackend\n"
            f"_LearningBackend(Path({str(root)!r})).store('correction', 'always run the tests', {{}}, 'repo')\n"
        )
        _run_workers(isolated_cognirepo, body, n=8)
        assert len(json.loads((root / "learnings.json").read_text())) == 1


class TestVectorStress:
    def test_vectors_from_8_processes_are_all_kept_and_aligned(self, isolated_cognirepo):
        """Each worker builds a FRESH LocalVectorDB per add — exactly what store_memory does."""
        body = (
            "import numpy as np\n"
            "from core.vector_db.local_vector_db import LocalVectorDB\n"
            "for i in range(15):\n"
            "    v = np.zeros(384, dtype='float32'); v[WORKER] = 1.0; v[100 + i] = 1.0\n"
            "    LocalVectorDB().add(v, f'w{WORKER}-v{i}', 0.5)\n"
        )
        _run_workers(isolated_cognirepo, body, n=8)
        from core.vector_db.local_vector_db import LocalVectorDB
        db = LocalVectorDB()
        assert db.index.ntotal == 120, f"lost {120 - db.index.ntotal} vectors"
        assert len(db.metadata) == 120
        assert len({m["text"] for m in db.metadata}) == 120
        for row, meta in enumerate(db.metadata):     # vector i must still belong to metadata i
            w, i = (int(x[1:]) for x in meta["text"].split("-"))
            vec = db.index.reconstruct(row)
            assert vec[w] == 1.0 and vec[100 + i] == 1.0, f"row {row} misaligned"

    def test_metadata_edits_beside_adds_lose_neither(self, isolated_cognirepo):
        import numpy as np
        from core.vector_db.local_vector_db import LocalVectorDB
        db = LocalVectorDB()
        for i in range(3):
            db.add(np.eye(384, dtype="float32")[i], f"seed{i}", 0.5)
        adder = (
            "import numpy as np\n"
            "from core.vector_db.local_vector_db import LocalVectorDB\n"
            "for i in range(20):\n"
            "    v = np.zeros(384, dtype='float32'); v[200 + i] = 1.0\n"
            "    LocalVectorDB().add(v, f'new{i}', 0.5)\n"
        )
        editor = (
            "from core.vector_db.local_vector_db import LocalVectorDB\n"
            "for i in range(20):\n"
            "    LocalVectorDB().update_behaviour_score(1, 0.1 * (i % 5))\n"
            "    LocalVectorDB().deprecate_row(2)\n"
        )
        env = dict(os.environ, COGNIREPO_DIR=str(isolated_cognirepo / ".cognirepo"))
        pre = f"import sys\nsys.path.insert(0, {_REPO!r})\n"
        procs = [subprocess.Popen([sys.executable, "-c", pre + b, "0"], cwd=isolated_cognirepo, env=env,
                                  stderr=subprocess.PIPE, text=True) for b in (adder, adder, editor)]
        for p in procs:
            _, err = p.communicate(timeout=180)
            assert p.returncode == 0, err[-500:]
        final = LocalVectorDB()
        assert final.index.ntotal == 3 + 40 and len(final.metadata) == 43
        assert final.metadata[2].get("deprecated") is True       # the edit survived the adds
        assert "behaviour_score" in final.metadata[1]

    def test_save_merges_into_newer_disk_state_instead_of_overwriting(self, isolated_cognirepo):
        import numpy as np
        from core.vector_db.local_vector_db import LocalVectorDB
        a, b = LocalVectorDB(), LocalVectorDB()       # both loaded the same (empty) state
        a.add(np.eye(384, dtype="float32")[0], "from-a", 0.5)
        b.add(np.eye(384, dtype="float32")[1], "from-b", 0.5)   # b's snapshot is stale now
        final = LocalVectorDB()
        assert final.index.ntotal == 2
        assert sorted(m["text"] for m in final.metadata) == ["from-a", "from-b"]
        assert np.allclose(final.index.reconstruct(0), np.eye(384, dtype="float32")[0])
        assert np.allclose(final.index.reconstruct(1), np.eye(384, dtype="float32")[1])

    def test_a_unreadable_disk_state_is_never_merged_over(self, isolated_cognirepo):
        import numpy as np
        from unittest import mock
        from core.config.safe_read import StoreUnreadableError
        from core.vector_db.local_vector_db import LocalVectorDB, _index_file
        a, b = LocalVectorDB(), LocalVectorDB()
        a.add(np.eye(384, dtype="float32")[0], "from-a", 0.5)
        good = open(_index_file(), "rb").read()
        open(_index_file(), "wb").write(good[: len(good) // 2])      # torn by something else
        with mock.patch("core.config.safe_read.time.sleep"):
            with pytest.raises(StoreUnreadableError):
                b.add(np.eye(384, dtype="float32")[1], "from-b", 0.5)
        assert open(_index_file(), "rb").read() == good[: len(good) // 2]   # not overwritten


class TestProjectMemoryStress:
    def test_shared_project_memory_from_4_processes_keeps_every_row(self, isolated_cognirepo, monkeypatch):
        base = isolated_cognirepo / "shared"
        body = (
            "import numpy as np\n"
            "from pathlib import Path\n"
            "from data.memory.project_memory import _ProjectLocalVectorDB\n"
            "for i in range(10):\n"
            f"    db = _ProjectLocalVectorDB(base=Path({str(base)!r}))\n"
            "    v = np.zeros(384, dtype='float32'); v[WORKER] = 1.0; v[50 + i] = 1.0\n"
            "    db.add(v, f'w{WORKER}-{i}', 0.5, 'repo')\n"
        )
        (base / "vector_db").mkdir(parents=True)
        (base / "memory").mkdir(parents=True)
        _run_workers(isolated_cognirepo, body, n=4)
        meta = json.loads((base / "memory" / "semantic_metadata.json").read_text())
        import faiss
        idx = faiss.read_index(str(base / "vector_db" / "semantic.index"))
        assert idx.ntotal == 40 and len(meta) == 40 and len({m["text"] for m in meta}) == 40
