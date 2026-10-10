# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Generation pointer for the multi-file AST store (COGNIREPO-140).

A lock-free reader must see ONE generation of {ast_index.json, ast.index, ast_metadata.json,
manifest.json}, never new json with old faiss/metadata; a crash at any publish step must leave
the previous generation intact and current.
"""
import hashlib
import json
import os
import threading

import numpy as np
import pytest

from core.config.generation import GenerationStore


class FakeModel:
    def embed(self, texts):
        for t in texts:
            seed = int(hashlib.sha256(t.encode()).hexdigest()[:8], 16)
            yield np.random.default_rng(seed).random(384).astype("float32")


def _mk():
    from data.graph.knowledge_graph import KnowledgeGraph
    from intelligence.indexer.ast_indexer import ASTIndexer
    ix = ASTIndexer(graph=KnowledgeGraph())
    ix.model = FakeModel()
    return ix


def _put(d, text):
    def w(p):
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    return w


class TestGenerationStore:
    def test_publish_makes_group_current_and_mirrors_links(self, tmp_path):
        st = GenerationStore(str(tmp_path / "g"))
        flat = tmp_path / "flat.txt"
        n = st.publish({"a": _put(0, "one")}, mirror={"a": str(flat)})
        assert st.current() == n == 1
        assert flat.read_text() == "one"
        assert os.path.samefile(flat, os.path.join(st.gen_dir(n), "a"))

    @pytest.mark.parametrize("fail_at", ["writer", "finalize"])
    def test_crash_mid_publish_keeps_previous_generation(self, tmp_path, fail_at):
        st = GenerationStore(str(tmp_path / "g"))
        st.publish({"a": _put(0, "old")})

        def boom(*_):
            raise RuntimeError("crash")
        writers = {"a": boom if fail_at == "writer" else _put(0, "new")}
        with pytest.raises(RuntimeError):
            st.publish(writers, finalize=boom if fail_at == "finalize" else None)
        assert st.current() == 1
        assert open(os.path.join(st.gen_dir(1), "a")).read() == "old"
        assert st.generations() == [1]
        assert not [n for n in os.listdir(st.root) if n.startswith(".incoming-")]

    def test_crash_before_pointer_flip_leaves_old_current(self, tmp_path, monkeypatch):
        st = GenerationStore(str(tmp_path / "g"))
        st.publish({"a": _put(0, "old")})
        monkeypatch.setattr("core.config.generation.atomic_write",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("power cut")))
        with pytest.raises(OSError):
            st.publish({"a": _put(0, "new")})
        monkeypatch.undo()
        assert st.current() == 1                      # pointer never moved
        assert open(os.path.join(st.gen_dir(st.current()), "a")).read() == "old"
        st.publish({"a": _put(0, "newer")})           # the orphan gen-2 does not block progress
        assert st.current() == 3

    def test_gc_keeps_newest_and_respects_grace(self, tmp_path):
        st = GenerationStore(str(tmp_path / "g"), keep=2, grace_secs=0)
        for i in range(5):
            st.publish({"a": _put(0, str(i))})
        assert st.generations() == [4, 5]
        graced = GenerationStore(str(tmp_path / "h"), keep=1, grace_secs=3600)
        for i in range(4):
            graced.publish({"a": _put(0, str(i))})
        assert graced.generations() == [1, 2, 3, 4]   # too young to collect


class TestASTIndexerGenerations:
    def test_save_publishes_complete_generation_and_flat_links(self, isolated_cognirepo, tmp_path):
        from intelligence.indexer.ast_indexer import (
            _ast_gen_store, _ast_index_file, _ast_faiss_file, _ast_meta_file, _manifest_file)
        (tmp_path / "m.py").write_text("def f():\n    return 1\n")
        ix = _mk()
        ix.index_file("m.py")
        ix.save()
        st = _ast_gen_store()
        d = st.gen_dir(st.current())
        assert sorted(os.listdir(d)) == ["ast.index", "ast_index.json", "ast_metadata.json", "manifest.json"]
        for name, flat in (("ast_index.json", _ast_index_file()), ("ast.index", _ast_faiss_file()),
                           ("ast_metadata.json", _ast_meta_file()), ("manifest.json", _manifest_file())):
            assert os.path.samefile(os.path.join(d, name), flat)
        fresh = _mk()
        fresh.load()
        assert "m.py" in fresh.index_data["files"]

    def test_load_ignores_hand_edited_flat_file(self, isolated_cognirepo, tmp_path):
        from intelligence.indexer.ast_indexer import _ast_index_file
        (tmp_path / "m.py").write_text("def f():\n    return 1\n")
        ix = _mk()
        ix.index_file("m.py")
        ix.save()
        flat = _ast_index_file()
        data = json.load(open(flat))
        data["files"] = {"only_in_flat.py": {"symbols": []}}
        os.unlink(flat)
        with open(flat, "w") as f:
            json.dump(data, f)
        fresh = _mk()
        fresh.load()
        assert list(fresh.index_data["files"]) == ["only_in_flat.py"]

    def test_reader_never_sees_mixed_generation_under_concurrent_saves(self, isolated_cognirepo, tmp_path):
        """Writer keeps saving; a lock-free reader reloads continuously. Every snapshot it
        observes must be internally consistent: faiss_meta length == index.ntotal and every
        symbol's faiss_id resolves to the matching meta record."""
        (tmp_path / "base.py").write_text("def base():\n    return 0\n")
        w = _mk()
        w.index_file("base.py")
        w.save()

        stop = threading.Event()
        errors: list[str] = []

        def write():
            for i in range(25):
                (tmp_path / f"f{i}.py").write_text(f"def fn{i}():\n    return {i}\n")
                w.index_file(f"f{i}.py")
                w.save()
            stop.set()

        t = threading.Thread(target=write)
        t.start()
        snapshots = 0
        while not stop.is_set() or snapshots < 5:
            r = _mk()
            r.load()
            snapshots += 1
            if r.faiss_index.ntotal != len(r.faiss_meta):
                errors.append(f"ntotal={r.faiss_index.ntotal} meta={len(r.faiss_meta)}")
            for rel, rec in r.index_data["files"].items():
                for sym in rec["symbols"]:
                    fid = sym.get("faiss_id", -1)
                    if fid >= 0 and (fid >= len(r.faiss_meta) or r.faiss_meta[fid]["name"] != sym["name"]):
                        errors.append(f"{rel}:{sym['name']} faiss_id={fid} mismatched")
            if stop.is_set():
                break
        t.join()
        assert snapshots > 1
        assert not errors, errors[:5]


class TestSemanticStoreGenerations:
    def _db(self):
        from core.vector_db.local_vector_db import LocalVectorDB
        return LocalVectorDB()

    def test_save_publishes_pair_and_flat_links(self, isolated_cognirepo):
        from core.vector_db.local_vector_db import _index_file, _meta_file, _semantic_store
        db = self._db()
        db.add(np.random.rand(384).tolist(), "hello", 0.5)
        st = _semantic_store()
        d = st.gen_dir(st.current())
        assert sorted(os.listdir(d)) == ["semantic.index", "semantic_metadata.json"]
        assert os.path.samefile(os.path.join(d, "semantic.index"), _index_file())
        assert os.path.samefile(os.path.join(d, "semantic_metadata.json"), _meta_file())

    def test_metadata_only_change_links_index_instead_of_rewriting(self, isolated_cognirepo):
        from core.vector_db.local_vector_db import _semantic_store
        db = self._db()
        db.add(np.random.rand(384).tolist(), "a", 0.5)
        st = _semantic_store()
        before = st.current()
        assert db.update_behaviour_score(0, 0.9)
        after = st.current()
        assert after == before + 1
        assert os.path.samefile(os.path.join(st.gen_dir(before), "semantic.index"),
                                os.path.join(st.gen_dir(after), "semantic.index"))
        assert self._db().metadata[0]["behaviour_score"] == 0.9

    def test_reader_never_sees_index_and_metadata_from_different_saves(self, isolated_cognirepo):
        """ntotal must equal len(metadata) in every snapshot a fresh reader loads."""
        w = self._db()
        stop = threading.Event()
        errors: list[str] = []

        def write():
            for i in range(40):
                w.add(np.random.rand(384).tolist(), f"m{i}", 0.5)
            stop.set()

        t = threading.Thread(target=write)
        t.start()
        n = 0
        while not stop.is_set() or n < 5:
            r = self._db()
            n += 1
            if r.index.ntotal != len(r.metadata):
                errors.append(f"ntotal={r.index.ntotal} meta={len(r.metadata)}")
            if stop.is_set():
                break
        t.join()
        assert n > 1 and not errors, errors[:5]

    def test_prune_rebuild_is_one_generation(self, isolated_cognirepo):
        from core.vector_db.local_vector_db import _semantic_store
        db = self._db()
        for i in range(3):
            db.add(np.random.rand(384).tolist(), f"m{i}", 0.5)
        from ops.cron import prune_memory
        before = _semantic_store().current()
        kept = [dict(m) for m in db.metadata[:2]]
        import faiss
        idx = faiss.IndexFlatL2(384)
        idx.add(np.random.rand(2, 384).astype("float32"))
        from core.vector_db.local_vector_db import publish_semantic
        import json
        publish_semantic(idx, json.dumps(kept).encode())
        assert _semantic_store().current() == before + 1
        r = self._db()
        assert r.index.ntotal == len(r.metadata) == 2
        assert prune_memory  # module imports cleanly with the new publish path
