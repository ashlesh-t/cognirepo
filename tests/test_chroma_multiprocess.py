# pylint: disable=missing-docstring, import-outside-toplevel, too-few-public-methods, protected-access
# pylint: disable=redefined-outer-name, unused-argument, duplicate-code
# SPDX-FileCopyrightText: 2026 Ashlesh T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_chroma_multiprocess.py — COGNIREPO-142.

Chroma is the default vector backend. Measured before the fix (6 real processes x 15 adds):
20 of 90 vectors survived and one process died creating the store. The causes were ours — ids
minted from ``count()`` collided across processes (chroma silently ignores an add of an existing
id), the first-time creation raced, and the open-sentinel logic could rename a healthy store.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

chromadb = pytest.importorskip("chromadb")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_workers(tmp_path, body: str, n: int, timeout: int = 240) -> None:
    pre = (
        "import os, sys\n"
        f"sys.path.insert(0, {_REPO!r})\n"
        "import numpy as np\n"
        "WORKER = int(sys.argv[1])\n"
        f"STORE = {str(tmp_path / 'store' / 'chroma')!r}\n"
    )
    env = dict(os.environ, COGNIREPO_DIR=str(tmp_path / ".cognirepo"))
    procs = [subprocess.Popen([sys.executable, "-c", pre + body, str(i)], cwd=tmp_path, env=env,  # pylint: disable=consider-using-with
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(n)]
    failures = []
    for i, p in enumerate(procs):
        _out, err = p.communicate(timeout=timeout)
        if p.returncode != 0:
            failures.append(f"worker {i}: {err[-700:]}")
    assert not failures, "\n".join(failures)


def _vec(slot: int, i: int = 0):
    import numpy as np
    v = np.zeros(384, dtype="float32")
    v[slot % 100] = 1.0
    v[100 + (i % 200)] = 1.0
    return v


def _read_all(store: str) -> dict:
    col = chromadb.PersistentClient(path=store).get_or_create_collection("cognirepo")
    return col.get(include=["documents"])


class TestMultiProcessAdds:
    def test_8_processes_creating_and_filling_a_new_store_lose_nothing(self, tmp_path):
        """The measured failure: concurrent first-time creation + colliding ids."""
        body = (
            "from core.vector_db.chroma_adapter import ChromaDBAdapter\n"
            "a = ChromaDBAdapter(path=STORE)\n"
            "for i in range(10):\n"
            "    v = np.zeros(384, dtype='float32'); v[WORKER] = 1.0; v[100 + i] = 1.0\n"
            "    a.add(v, f'w{WORKER}-d{i}', 0.5)\n"
        )
        _run_workers(tmp_path, body, n=8)
        got = _read_all(str(tmp_path / "store" / "chroma"))
        assert len(got["ids"]) == 80, f"lost {80 - len(got['ids'])} vectors"
        assert len(set(got["ids"])) == 80 and len(set(got["documents"])) == 80
        assert all(i.isdigit() for i in got["ids"]), "ids must stay numeric strings (callers use them as row ids)"

    def test_vectors_are_searchable_by_a_fresh_process_after_concurrent_adds(self, tmp_path):
        body = (
            "from core.vector_db.chroma_adapter import ChromaDBAdapter\n"
            "a = ChromaDBAdapter(path=STORE)\n"
            "for i in range(6):\n"
            "    v = np.zeros(384, dtype='float32'); v[WORKER] = 1.0; v[100 + i] = 1.0\n"
            "    a.add(v, f'w{WORKER}-d{i}', 0.5)\n"
        )
        _run_workers(tmp_path, body, n=4)
        from core.vector_db.chroma_adapter import ChromaDBAdapter
        db = ChromaDBAdapter(path=str(tmp_path / "store" / "chroma"))
        for w, i in ((0, 0), (1, 3), (2, 5), (3, 2)):
            v = _vec(w, i)
            v[:] = 0
            v[w] = 1.0
            v[100 + i] = 1.0
            assert db.search(v, top_k=1)[0]["text"] == f"w{w}-d{i}"

    def test_add_batch_ids_are_unique_across_processes(self, tmp_path):
        body = (
            "from core.vector_db.chroma_adapter import ChromaDBAdapter\n"
            "a = ChromaDBAdapter(path=STORE)\n"
            "entries = []\n"
            "for i in range(5):\n"
            "    v = np.zeros(384, dtype='float32'); v[WORKER] = 1.0; v[100 + i] = 1.0\n"
            "    entries.append((v, f'b{WORKER}-{i}', 0.5))\n"
            "assert a.add_batch(entries) == 5\n"
        )
        _run_workers(tmp_path, body, n=5)
        got = _read_all(str(tmp_path / "store" / "chroma"))
        assert len(got["ids"]) == 25 and len(set(got["documents"])) == 25

    def test_writers_racing_readers_and_metadata_updates_raise_nothing(self, tmp_path):
        writer = (
            "from core.vector_db.chroma_adapter import ChromaDBAdapter\n"
            "a = ChromaDBAdapter(path=STORE)\n"
            "for i in range(8):\n"
            "    v = np.zeros(384, dtype='float32'); v[WORKER] = 1.0; v[100 + i] = 1.0\n"
            "    a.add(v, f'w{WORKER}-d{i}', 0.5)\n"
            "    a.update_behaviour_score(0, 0.1 * (i % 5))\n"
        )
        reader = (
            "from core.vector_db.chroma_adapter import ChromaDBAdapter\n"
            "a = ChromaDBAdapter(path=STORE)\n"
            "q = np.zeros(384, dtype='float32'); q[0] = 1.0\n"
            "for _ in range(15):\n"
            "    a.search(q, top_k=3); a.count()\n"
        )
        env = dict(os.environ, COGNIREPO_DIR=str(tmp_path / ".cognirepo"))
        pre = f"import sys\nsys.path.insert(0, {_REPO!r})\nimport numpy as np\nWORKER = int(sys.argv[1])\nSTORE = {str(tmp_path / 'store' / 'chroma')!r}\n"
        procs = [subprocess.Popen([sys.executable, "-c", pre + (writer if i < 4 else reader), str(i)], cwd=tmp_path,  # pylint: disable=consider-using-with
                                  env=env, stderr=subprocess.PIPE, text=True) for i in range(6)]
        for p in procs:
            _o, err = p.communicate(timeout=240)
            assert p.returncode == 0, err[-600:]
        assert len(_read_all(str(tmp_path / "store" / "chroma"))["ids"]) == 32

    def test_through_the_factory_with_concurrent_openers(self, tmp_path):
        """Every opener writes its own sentinel/marker — none may clobber another's."""
        (tmp_path / ".cognirepo").mkdir(exist_ok=True)
        (tmp_path / ".cognirepo" / "config.json").write_text(json.dumps({"storage": {"vector_backend": "chroma"}}))
        body = (
            "from core.vector_db.factory import get_vector_adapter\n"
            "a = get_vector_adapter()\n"
            "for i in range(5):\n"
            "    v = np.zeros(384, dtype='float32'); v[WORKER] = 1.0; v[100 + i] = 1.0\n"
            "    a.add(v, f'f{WORKER}-{i}', 0.5)\n"
        )
        _run_workers(tmp_path, body, n=6)
        got = _read_all(str(tmp_path / ".cognirepo" / "vector_db" / "chroma"))
        assert len(got["ids"]) == 30 and len(set(got["documents"])) == 30
        corrupt = list((tmp_path / ".cognirepo" / "vector_db").glob("chroma.corrupt-*"))
        assert not corrupt, f"a healthy store was quarantined: {corrupt}"


class TestIdAllocation:
    def _db(self, tmp_path):
        from core.vector_db.chroma_adapter import ChromaDBAdapter
        return ChromaDBAdapter(path=str(tmp_path / "chroma"))

    def test_an_add_after_a_remove_does_not_collide(self, tmp_path):
        """count() < highest id after a delete, so the old scheme re-minted a live id and chroma
        silently dropped the new vector."""
        db = self._db(tmp_path)
        for i in range(10):
            db.add(_vec(1, i), f"doc{i}", 0.5)
        db.remove([3, 4])
        for i in range(3):
            db.add(_vec(2, i), f"new{i}", 0.5)
        docs = _read_all(str(tmp_path / "chroma"))["documents"]
        assert len(docs) == 11 and {"new0", "new1", "new2"} <= set(docs)

    def test_a_legacy_store_without_a_counter_continues_after_its_highest_id(self, tmp_path):
        store = str(tmp_path / "chroma")
        col = chromadb.PersistentClient(path=store).get_or_create_collection("cognirepo", metadata={"hnsw:space": "l2"})
        col.add(ids=[str(i) for i in range(10)], embeddings=[_vec(1, i).tolist() for i in range(10)],
                documents=[f"old{i}" for i in range(10)])
        assert not os.path.exists(os.path.join(store, ".next_id"))
        db = self._db(tmp_path)
        db.add(_vec(5, 0), "after-upgrade", 0.5)
        got = _read_all(store)
        assert len(got["ids"]) == 11 and "10" in got["ids"]

    def test_next_id_minus_one_is_the_id_just_stored(self, tmp_path):
        """interface/server/mcp_server.py reads ``str(db._next_id - 1)`` right after an add."""
        db = self._db(tmp_path)
        db.add(_vec(1, 1), "first", 0.5)
        db.add(_vec(1, 2), "second", 0.5)
        stored_id = str(db._next_id - 1)
        col = chromadb.PersistentClient(path=str(tmp_path / "chroma")).get_or_create_collection("cognirepo")
        assert col.get(ids=[stored_id], include=["documents"])["documents"] == ["second"]

    def test_the_counter_never_goes_below_the_live_count(self, tmp_path):
        """Defends against an older writer that still allocates ids from count()."""
        db = self._db(tmp_path)
        for i in range(3):
            db.add(_vec(1, i), f"d{i}", 0.5)
        (tmp_path / "chroma" / ".next_id").write_text("1")           # stale/lost counter
        db.add(_vec(2, 0), "after", 0.5)
        assert len(_read_all(str(tmp_path / "chroma"))["ids"]) == 4

    def test_a_lost_counter_is_rebuilt_from_the_highest_id(self, tmp_path):
        db = self._db(tmp_path)
        for i in range(4):
            db.add(_vec(1, i), f"d{i}", 0.5)
        os.unlink(tmp_path / "chroma" / ".next_id")
        db.add(_vec(2, 0), "after", 0.5)
        assert len(_read_all(str(tmp_path / "chroma"))["ids"]) == 5


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])  # pylint: disable=consider-using-with
    p.wait()
    return p.pid


class TestOpenSentinel:
    @pytest.fixture
    def factory(self, isolated_cognirepo):
        (Path(".cognirepo") / "config.json").write_text(json.dumps({"storage": {"vector_backend": "chroma"}}))
        from core.vector_db import factory
        return factory

    def _healthy_store(self, factory, docs=3):
        adapter = factory.get_vector_adapter()
        for i in range(docs):
            adapter.add(_vec(1, i), f"doc{i}", 0.5)
        return factory._get_vector_db_path()

    def _stale_sentinel(self, factory, store: Path, pid: "int | None" = None):
        pid = pid or _dead_pid()
        (store / f"{factory._SENTINEL_PREFIX}{pid}").write_text(json.dumps({"pid": pid, "start": "1", "ts": 0}))

    def test_a_killed_opener_does_not_cost_a_healthy_store_its_data(self, factory):
        """The bug: any dead-pid sentinel made the next process rename the whole store."""
        store = self._healthy_store(factory)
        self._stale_sentinel(factory, store)
        adapter = factory.get_vector_adapter()
        assert adapter.count() == 3
        assert not list(store.parent.glob("chroma.corrupt-*")), "a healthy store was quarantined"
        assert not [n for n in os.listdir(store) if n.startswith(factory._SENTINEL_PREFIX)]

    def test_a_legacy_bare_pid_sentinel_is_also_not_poison(self, factory):
        store = self._healthy_store(factory)
        (store / ".opening").write_text(str(_dead_pid()))                 # the old single shared file
        (store / f"{factory._SENTINEL_PREFIX}{_dead_pid()}").write_text(str(_dead_pid()))
        assert factory.get_vector_adapter().count() == 3
        assert not list(store.parent.glob("chroma.corrupt-*"))

    def test_a_live_peer_prevents_any_quarantine_and_any_probe(self, factory, monkeypatch):
        store = self._healthy_store(factory)
        self._stale_sentinel(factory, store)
        peer = subprocess.Popen(["sleep", "60"])  # pylint: disable=consider-using-with
        try:
            (store / f"{factory._MARKER_PREFIX}{peer.pid}").write_text(
                json.dumps({"pid": peer.pid, "start": factory._proc_start(peer.pid), "ts": time.time()}))
            probed = []
            monkeypatch.setattr(factory, "_probe_store", lambda p: probed.append(p) or False)  # would "fail"
            quarantined = []
            monkeypatch.setattr(factory, "quarantine_chroma_store", lambda p=None: quarantined.append(p))
            factory._heal_crashed_chroma(store)
            assert not quarantined and not probed
            assert not [n for n in os.listdir(store) if n.startswith(factory._SENTINEL_PREFIX)]
        finally:
            peer.kill()
            peer.wait()

    def test_a_poisoned_store_nobody_holds_is_quarantined_and_kept(self, factory):
        store = self._healthy_store(factory)
        garbage = b"this is not a sqlite database" * 50
        (store / "chroma.sqlite3").write_bytes(garbage)
        self._stale_sentinel(factory, store)
        adapter = factory.get_vector_adapter()          # heals: probe fails -> quarantine -> fresh store
        kept = list(store.parent.glob("chroma.corrupt-*"))
        assert len(kept) == 1 and (kept[0] / "chroma.sqlite3").read_bytes() == garbage
        assert adapter.count() == 0

    def test_sentinels_are_per_process(self, factory):
        """One shared file let a finishing opener erase another opener's crash evidence."""
        store = factory._get_vector_db_path()
        store.mkdir(parents=True, exist_ok=True)
        other = subprocess.Popen(["sleep", "60"])  # pylint: disable=consider-using-with
        try:
            mine_other = store / f"{factory._SENTINEL_PREFIX}{other.pid}"
            mine_other.write_text(json.dumps({"pid": other.pid, "start": factory._proc_start(other.pid), "ts": time.time()}))
            factory.get_vector_adapter()
            assert mine_other.exists(), "another opener's sentinel was erased"
            assert not (store / f"{factory._SENTINEL_PREFIX}{os.getpid()}").exists()
        finally:
            other.kill()
            other.wait()

    def test_a_live_opener_is_not_treated_as_a_crash(self, factory):
        store = self._healthy_store(factory)
        other = subprocess.Popen(["sleep", "60"])  # pylint: disable=consider-using-with
        try:
            (store / f"{factory._SENTINEL_PREFIX}{other.pid}").write_text(
                json.dumps({"pid": other.pid, "start": factory._proc_start(other.pid), "ts": time.time()}))
            factory._heal_crashed_chroma(store)
            assert (store / f"{factory._SENTINEL_PREFIX}{other.pid}").exists()
            assert not list(store.parent.glob("chroma.corrupt-*"))
        finally:
            other.kill()
            other.wait()

    @pytest.mark.skipif(not os.path.exists("/proc/self/stat"), reason="needs /proc")
    def test_pid_reuse_is_detected_by_start_time(self, factory):
        mine = factory._proc_start(os.getpid())
        assert factory._is_live({"pid": os.getpid(), "start": mine})
        assert not factory._is_live({"pid": os.getpid(), "start": "1"}), \
            "same pid but a different start time is a different process"

    def test_a_normal_open_leaves_no_sentinel_but_registers_a_marker(self, factory):
        store = self._healthy_store(factory, docs=1)
        names = os.listdir(store)
        assert not [n for n in names if n.startswith(factory._SENTINEL_PREFIX)]
        assert f"{factory._MARKER_PREFIX}{os.getpid()}" in names

    def test_an_exception_while_opening_still_removes_the_sentinel(self, factory, monkeypatch):
        """A Python exception is not a native crash: only a crash may leave evidence behind."""
        import core.vector_db.chroma_adapter as ca

        def boom(self, *a, **k):
            raise RuntimeError("open failed")
        monkeypatch.setattr(ca.ChromaDBAdapter, "__init__", boom)
        with pytest.raises(RuntimeError):
            factory.get_vector_adapter()
        store = factory._get_vector_db_path()
        assert not [n for n in os.listdir(store) if n.startswith(factory._SENTINEL_PREFIX)]


class TestPathResolution:
    def test_the_store_follows_the_active_cognirepo_dir(self, isolated_cognirepo):
        from core.config.paths import get_cognirepo_dir
        from core.vector_db import factory
        assert factory._get_vector_db_path() == Path(get_cognirepo_dir()) / "vector_db" / "chroma"

    def test_config_is_read_from_the_active_dir_not_a_parent_walk(self, isolated_cognirepo, tmp_path, monkeypatch):
        """The old _find_config walked up from cwd and could read another project's config."""
        outer = tmp_path / "outer"
        (outer / ".cognirepo").mkdir(parents=True)
        (outer / ".cognirepo" / "config.json").write_text(json.dumps({"storage": {"vector_backend": "faiss"}}))
        inner = outer / "sub" / "dir"
        inner.mkdir(parents=True)
        monkeypatch.chdir(inner)
        from core.vector_db import factory
        assert factory._read_backend() == "chroma"        # the ACTIVE dir has no setting -> default
        (Path(".") / ".cognirepo").mkdir(exist_ok=True)

    def test_an_unconfigured_store_never_falls_back_to_the_real_home(self, isolated_cognirepo, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(fake_home))
        from core.vector_db import factory
        assert not str(factory._get_vector_db_path()).startswith(str(fake_home))
