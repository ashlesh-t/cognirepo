# pylint: disable=missing-docstring, import-outside-toplevel, too-few-public-methods, protected-access
# pylint: disable=redefined-outer-name, unused-argument, duplicate-code
# SPDX-FileCopyrightText: 2026 Ashlesh T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_side_effect_free_readers.py — COGNIREPO-135.

Readers must never rename, sweep or overwrite a store because a read failed: the failure may
be a concurrent writer or a missing decryption key. Only a writer may quarantine, and only a
file that stays unreadable and unchanged.
"""
from __future__ import annotations

import json
import os
import pathlib
import threading
import time
from unittest import mock

import pytest

from core.config.safe_read import (
    StoreUnreadableError, looks_encrypted, quarantine_if_stably_corrupt, read_retry,
)


def _names(directory, prefix: str) -> list[str]:
    return sorted(n for n in os.listdir(directory) if n.startswith(prefix))


# ── shared helper ─────────────────────────────────────────────────────────────

class TestSafeReadHelper:
    def test_read_retry_heals_a_transient_failure(self, tmp_path):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ValueError("torn")
            return "ok"
        assert read_retry(str(tmp_path / "x"), flaky, delay=0.001) == "ok" and calls["n"] == 3

    def test_read_retry_raises_after_attempts_without_touching_anything(self, tmp_path):
        f = tmp_path / "x.json"
        f.write_text("{broken")
        with pytest.raises(StoreUnreadableError) as exc:
            read_retry(str(f), lambda: json.loads(f.read_text()), delay=0.001)
        assert not exc.value.locked and f.read_text() == "{broken"
        assert _names(tmp_path, "x.json") == ["x.json"]

    def test_missing_file_is_not_an_error_state(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_retry(str(tmp_path / "nope"), lambda: open(tmp_path / "nope").read())

    def test_looks_encrypted(self):
        assert looks_encrypted(b"gAAAAABhxyz") and not looks_encrypted(b'{"a": 1}')

    def test_quarantine_only_when_stably_corrupt_and_keeps_the_bytes(self, tmp_path):
        f = tmp_path / "s.json"
        f.write_bytes(b"{garbage")
        moved = quarantine_if_stably_corrupt(str(f), lambda: False, settle=0.01)
        assert moved and not f.exists() and pathlib.Path(moved).read_bytes() == b"{garbage"

    def test_quarantine_skips_a_readable_file(self, tmp_path):
        f = tmp_path / "s.json"
        f.write_text("{}")
        assert quarantine_if_stably_corrupt(str(f), lambda: True) is None and f.exists()

    def test_quarantine_skips_a_file_that_changes_while_we_look(self, tmp_path):
        f = tmp_path / "s.json"
        f.write_text("{partial")

        def writer_lands():            # a concurrent writer rewrites it during the settle window
            f.write_text("{partial but longer")
        with mock.patch("core.config.safe_read.time.sleep", side_effect=lambda _s: writer_lands()):
            assert quarantine_if_stably_corrupt(str(f), lambda: False) is None
        assert f.exists()

    def test_quarantine_skips_a_file_that_heals(self, tmp_path):
        f = tmp_path / "s.json"
        f.write_text("{partial")
        state = {"calls": 0}

        def readable():                # unreadable on the first look, fine on the second
            state["calls"] += 1
            return state["calls"] > 1
        assert quarantine_if_stably_corrupt(str(f), readable, settle=0.001) is None and f.exists()


# ── episodic ──────────────────────────────────────────────────────────────────

class TestEpisodic:
    def test_forced_decode_error_is_never_followed_by_a_save_of_empty(self, isolated_cognirepo):
        """The issue's acceptance test."""
        from data.memory import episodic_memory as ep
        ep.log_event("precious history", {})
        before = open(ep._file_path(), "rb").read()
        with mock.patch.object(ep, "_read_store", side_effect=ValueError("decode")), \
             mock.patch("core.config.safe_read.time.sleep"), \
             mock.patch.object(ep, "_save") as save:
            assert ep.get_history() == []                       # readers degrade quietly …
            assert ep.search_episodes("precious") == []
            with pytest.raises(StoreUnreadableError):           # … a writer refuses …
                with mock.patch("data.memory.episodic_memory.quarantine_if_stably_corrupt",
                                return_value=None):
                    ep.log_event("new", {})
            save.assert_not_called()                            # … and nobody saved []
        assert open(ep._file_path(), "rb").read() == before

    def test_reader_never_renames_a_corrupt_store(self, isolated_cognirepo):
        from data.memory import episodic_memory as ep
        ep.log_event("one", {})
        path = ep._file_path()
        open(path, "wb").write(b"{not json")
        with mock.patch("core.config.safe_read.time.sleep"):
            assert ep.get_history() == []
            assert ep.search_episodes("x") == []
        assert open(path, "rb").read() == b"{not json"
        assert _names(os.path.dirname(path), "episodic.json") == ["episodic.json"]

    def test_writer_quarantines_stable_corruption_and_preserves_the_bytes(self, isolated_cognirepo):
        from data.memory import episodic_memory as ep
        ep.log_event("one", {})
        path = ep._file_path()
        open(path, "wb").write(b"{not json")
        with mock.patch("core.config.safe_read.time.sleep"):
            ep.log_event("after recovery", {})
        kept = _names(os.path.dirname(path), "episodic.json.corrupt-")
        assert len(kept) == 1
        assert open(os.path.join(os.path.dirname(path), kept[0]), "rb").read() == b"{not json"
        assert [e["event"] for e in ep.get_history()] == ["after recovery"]

    def test_locked_ciphertext_is_never_quarantined_or_overwritten(self, isolated_cognirepo):
        pytest.importorskip("cryptography")
        from data.memory import episodic_memory as ep
        path = ep._file_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ciphertext = b"gAAAAAB" + b"x" * 200            # intact Fernet-looking token
        open(path, "wb").write(ciphertext)
        pathlib.Path(".cognirepo/config.json").write_text(
            json.dumps({"project_id": "p", "storage": {"encrypt": True}}))
        with mock.patch("core.security.encryption.get_or_create_key", side_effect=RuntimeError("no key")), \
             mock.patch("core.config.safe_read.time.sleep"):
            with pytest.raises(StoreUnreadableError) as exc:
                ep.log_event("must not overwrite", {})
            assert exc.value.locked
            assert ep.get_history() == []
        assert open(path, "rb").read() == ciphertext
        assert _names(os.path.dirname(path), "episodic.json") == ["episodic.json"]

    def test_unreadable_archive_means_no_rotation_and_no_lost_history(self, isolated_cognirepo):
        from data.memory import episodic_memory as ep
        for i in range(5):
            ep.log_event(f"e{i}", {})
        apath = ep._archive_path()
        open(apath, "wb").write(b"{broken archive")
        with mock.patch.object(ep, "_get_max_events", return_value=3), \
             mock.patch("core.config.safe_read.time.sleep"):
            ep.log_event("one more", {})
        assert len(ep.get_history(limit=100)) == 6          # nothing trimmed away
        assert open(apath, "rb").read() == b"{broken archive"

    def test_concurrent_writer_never_makes_a_reader_mutate_anything(self, isolated_cognirepo):
        from data.memory import episodic_memory as ep
        ep.log_event("seed", {})
        directory = os.path.dirname(ep._file_path())
        stop = threading.Event()

        def writer():
            i = 0
            while not stop.is_set() and i < 150:
                ep.log_event(f"w{i}", {})
                i += 1
        t = threading.Thread(target=writer)
        t.start()
        try:
            for _ in range(150):
                ep.get_history(limit=5)
        finally:
            stop.set()
            t.join()
        assert _names(directory, "episodic.json.corrupt") == []
        assert len(ep.get_history(limit=1000)) >= 2


# ── learnings ─────────────────────────────────────────────────────────────────

class TestLearnings:
    def _store(self, tmp_path):
        from data.memory.learning_store import _LearningBackend
        return _LearningBackend(tmp_path / "learn")

    def test_reader_gets_nothing_and_changes_nothing(self, tmp_path):
        s = self._store(tmp_path)
        (tmp_path / "learn" / "learnings.json").write_text("{bad")
        with mock.patch("core.config.safe_read.time.sleep"):
            assert s.retrieve("anything") == []
        assert (tmp_path / "learn" / "learnings.json").read_text() == "{bad"
        assert _names(tmp_path / "learn", "learnings.json") == ["learnings.json"]

    def test_unreadable_store_is_not_overwritten_by_an_empty_one(self, tmp_path):
        s = self._store(tmp_path)
        (tmp_path / "learn" / "learnings.json").write_text("{bad")
        with mock.patch("core.config.safe_read.time.sleep"), \
             mock.patch("data.memory.learning_store.quarantine_if_stably_corrupt", return_value=None):
            with pytest.raises(StoreUnreadableError):
                s.store("correction", "do not wipe me", {}, "repo")
        assert (tmp_path / "learn" / "learnings.json").read_text() == "{bad"

    def test_writer_quarantines_stable_corruption(self, tmp_path):
        s = self._store(tmp_path)
        (tmp_path / "learn" / "learnings.json").write_text("{bad")
        with mock.patch("core.config.safe_read.time.sleep"):
            s.store("correction", "fresh start", {}, "repo")
        assert len(_names(tmp_path / "learn", "learnings.json.corrupt-")) == 1
        assert len(json.loads((tmp_path / "learn" / "learnings.json").read_text())) == 1


# ── vector store ──────────────────────────────────────────────────────────────

class TestLocalVectorDB:
    def test_constructing_it_never_renames_a_corrupt_index(self, isolated_cognirepo):
        from core.vector_db.local_vector_db import LocalVectorDB, _index_file
        db = LocalVectorDB()
        db.save()
        open(_index_file(), "wb").write(b"not a faiss index")
        with mock.patch("core.config.safe_read.time.sleep"):
            for _ in range(3):                       # SemanticMemory() is built per store_memory
                LocalVectorDB()
        assert open(_index_file(), "rb").read() == b"not a faiss index"
        assert _names(os.path.dirname(_index_file()), "semantic.index") == ["semantic.index"]

    def test_corrupt_metadata_is_not_overwritten_with_empty_on_load(self, isolated_cognirepo):
        from core.vector_db.local_vector_db import LocalVectorDB, _meta_file
        LocalVectorDB()
        open(_meta_file(), "wb").write(b"{bad json")
        with mock.patch("core.config.safe_read.time.sleep"):
            db = LocalVectorDB()
        assert db.metadata == [] and open(_meta_file(), "rb").read() == b"{bad json"
        assert _names(os.path.dirname(_meta_file()), "semantic_metadata.json") == ["semantic_metadata.json"]

    def test_save_refuses_over_a_store_that_failed_to_load(self, isolated_cognirepo):
        from core.vector_db.local_vector_db import LocalVectorDB, _index_file
        LocalVectorDB().save()
        open(_index_file(), "wb").write(b"junk")
        with mock.patch("core.config.safe_read.time.sleep"):
            db = LocalVectorDB()
            with mock.patch("core.vector_db.local_vector_db.quarantine_if_stably_corrupt",
                            return_value=None):
                with pytest.raises(StoreUnreadableError):
                    db.save()
        assert open(_index_file(), "rb").read() == b"junk"

    def test_save_quarantines_stable_corruption_then_writes(self, isolated_cognirepo):
        import faiss
        from core.vector_db.local_vector_db import LocalVectorDB, _index_file
        LocalVectorDB().save()
        open(_index_file(), "wb").write(b"junk")
        with mock.patch("core.config.safe_read.time.sleep"):
            db = LocalVectorDB()
            db.save()
        directory = os.path.dirname(_index_file())
        kept = _names(directory, "semantic.index.corrupt-")
        assert len(kept) == 1 and open(os.path.join(directory, kept[0]), "rb").read() == b"junk"
        assert faiss.read_index(_index_file()).ntotal == 0

    def test_locked_metadata_is_never_quarantined(self, isolated_cognirepo):
        pytest.importorskip("cryptography")
        from core.vector_db.local_vector_db import LocalVectorDB, _meta_file
        LocalVectorDB()
        ciphertext = b"gAAAAAB" + b"y" * 100
        open(_meta_file(), "wb").write(ciphertext)
        pathlib.Path(".cognirepo/config.json").write_text(
            json.dumps({"project_id": "p", "storage": {"encrypt": True}}))
        with mock.patch("core.security.encryption.get_or_create_key", side_effect=RuntimeError("no key")), \
             mock.patch("core.config.safe_read.time.sleep"):
            db = LocalVectorDB()
            with pytest.raises(StoreUnreadableError) as exc:
                db.save()
        assert exc.value.locked and open(_meta_file(), "rb").read() == ciphertext

    def test_a_store_that_heals_is_not_quarantined(self, isolated_cognirepo):
        from core.vector_db.local_vector_db import LocalVectorDB, _meta_file
        LocalVectorDB()
        good = open(_meta_file(), "rb").read()
        open(_meta_file(), "wb").write(b"{torn")
        with mock.patch("core.config.safe_read.time.sleep"):
            db = LocalVectorDB()                   # saw the torn file
        open(_meta_file(), "wb").write(good)       # writer finished
        with pytest.raises(StoreUnreadableError, match="readable now"):
            db._ensure_writable()
        assert open(_meta_file(), "rb").read() == good


# ── AST index ─────────────────────────────────────────────────────────────────

class TestASTIndexerLoad:
    def _idx(self):
        from data.graph.knowledge_graph import KnowledgeGraph
        from intelligence.indexer.ast_indexer import ASTIndexer
        return ASTIndexer(graph=KnowledgeGraph())

    def _seed(self):
        from intelligence.indexer.ast_indexer import _ast_index_file, _ast_meta_file
        idx = self._idx()
        idx._ensure_faiss()
        idx.index_data["files"] = {"a.py": {"symbols": []}}
        idx.save()
        return _ast_index_file(), _ast_meta_file()

    def test_load_never_renames_a_corrupt_index(self, isolated_cognirepo):
        index_file, _ = self._seed()
        open(index_file, "wb").write(b'{"files": {"a.py": {"sym')
        with mock.patch("core.config.safe_read.time.sleep"):
            self._idx().load()
        assert open(index_file, "rb").read() == b'{"files": {"a.py": {"sym'
        assert _names(os.path.dirname(index_file), "ast_index.json") == ["ast_index.json"]

    def test_save_refuses_to_overwrite_an_unreadable_index_then_quarantines_when_stable(self, isolated_cognirepo):
        index_file, _ = self._seed()
        open(index_file, "wb").write(b"{broken")
        with mock.patch("core.config.safe_read.time.sleep"):
            idx = self._idx()
            idx.load()
            with mock.patch("intelligence.indexer.ast_indexer.quarantine_if_stably_corrupt",
                            return_value=None):
                with pytest.raises(StoreUnreadableError):
                    idx.save()
            assert open(index_file, "rb").read() == b"{broken"
            idx.save()                                   # stable corruption → quarantine, then write
        kept = _names(os.path.dirname(index_file), "ast_index.json.corrupt-")
        assert len(kept) == 1
        assert json.load(open(index_file))["files"] == {}

    def test_corrupt_faiss_binary_is_not_renamed_on_load(self, isolated_cognirepo):
        from intelligence.indexer.ast_indexer import _ast_faiss_file
        index_file, _ = self._seed()
        open(_ast_faiss_file(), "wb").write(b"not faiss")
        with mock.patch("core.config.safe_read.time.sleep"):
            self._idx().load()
        assert open(_ast_faiss_file(), "rb").read() == b"not faiss"
        assert _names(os.path.dirname(_ast_faiss_file()), "ast.index") == ["ast.index"]

    def test_platform_mismatch_is_renamed_by_the_writer_not_by_load(self, isolated_cognirepo):
        from intelligence.indexer.ast_indexer import _ast_faiss_file
        self._seed()
        faiss_file = _ast_faiss_file()
        assert os.path.exists(faiss_file)
        with mock.patch("intelligence.indexer.ast_indexer._check_platform_compat", return_value=False):
            idx = self._idx()
            idx.load()
            assert os.path.exists(faiss_file) and not os.path.exists(faiss_file + ".stale")
        idx.save()                                       # the writer moves it aside, explicitly
        assert os.path.exists(faiss_file + ".stale")

    def test_sweep_does_not_run_while_another_process_holds_the_store_lock(self, isolated_cognirepo):
        from core.config.lock import store_lock
        from intelligence.indexer.ast_indexer import _ast_index_file
        self._seed()
        scratch = _ast_index_file() + ".old123.tmp"
        open(scratch, "w").write("stale")
        old = time.time() - 7200
        os.utime(scratch, (old, old))
        held, release = threading.Event(), threading.Event()

        def other_writer():                              # a DIFFERENT holder (the lock is
            with store_lock():                           # re-entrant for the same thread)
                held.set()
                release.wait(10)
        t = threading.Thread(target=other_writer)
        t.start()
        assert held.wait(10)
        try:
            self._idx().load()
        finally:
            release.set()
            t.join()
        assert os.path.exists(scratch), "sweep must not delete files without the lock"
        self._idx().load()                               # lock free + old enough → swept
        assert not os.path.exists(scratch)
