# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""ASTIndexer.save() rebases onto a newer on-disk index instead of overwriting it (COGNIREPO-139).

Before: a long-lived writer (watcher) that had loaded the index earlier saved its private copy over
whatever ``index-repo`` had written since — files indexed in between vanished from ast_index.json /
ast.index / ast_metadata.json while the graph (which already rebased) still had them.
"""
import hashlib
import os
import subprocess
import sys
import textwrap

import numpy as np
import pytest


class FakeModel:
    """Deterministic 384-d embeddings — no model download."""

    def embed(self, texts):
        for t in texts:
            seed = int(hashlib.sha256(t.encode()).hexdigest()[:8], 16)
            yield np.random.default_rng(seed).random(384).astype("float32")


def _mk(embed=True):
    from data.graph.knowledge_graph import KnowledgeGraph
    from intelligence.indexer.ast_indexer import ASTIndexer
    kg = KnowledgeGraph()
    ix = ASTIndexer(graph=kg)
    if embed:
        ix.model = FakeModel()
    else:
        ix._embed_enabled = False  # pylint: disable=protected-access
    return ix, kg


def _write(tmp_path, name, fn, body="return 1"):
    (tmp_path / name).write_text(f"def {fn}():\n    {body}\n")


def _assert_consistent(ix):
    """Every live symbol's faiss_id points at a meta record for that symbol, with a vector."""
    for rel, rec in ix.index_data["files"].items():
        for sym in rec["symbols"]:
            fid = sym.get("faiss_id", -1)
            if fid < 0:
                continue
            assert ix.faiss_meta[fid]["name"] == sym["name"] and ix.faiss_meta[fid]["file"] == rel
            assert ix.faiss_index.reconstruct(int(fid)).shape == (384,)


@pytest.fixture()
def seeded(isolated_cognirepo, tmp_path):
    _write(tmp_path, "base.py", "base_fn")
    s, sg = _mk()
    s.index_file("base.py")
    s.save()
    sg.save()
    return tmp_path


class TestRebase:
    def test_stale_writer_keeps_the_other_writers_file(self, seeded):
        tmp = seeded
        _write(tmp, "a.py", "from_a")
        _write(tmp, "b.py", "from_b")
        a, _ = _mk(); a.load()                                  # long-lived watcher
        b, _ = _mk(); b.load(); b.index_file("b.py"); b.save()  # index-repo finishes later
        a.index_file("a.py"); a.save()                          # watcher's next event
        r, _ = _mk(); r.load()
        assert sorted(r.index_data["files"]) == ["a.py", "b.py", "base.py"]
        for name in ("from_a", "from_b", "base_fn"):
            assert r.lookup_symbol(name), name
        assert r.index_data["total_symbols"] == 3

    def test_vectors_of_both_writers_survive_and_ids_are_consistent(self, seeded):
        tmp = seeded
        _write(tmp, "a.py", "from_a")
        _write(tmp, "b.py", "from_b")
        a, _ = _mk(); a.load()
        b, _ = _mk(); b.load(); b.index_file("b.py"); b.save()
        a.index_file("a.py"); a.save()
        r, _ = _mk(); r.load()
        _assert_consistent(r)
        names = {m["name"] for m in r.faiss_meta}
        assert {"from_a", "from_b", "base_fn"} <= names
        live = [s["faiss_id"] for f in r.index_data["files"].values() for s in f["symbols"]]
        assert len(live) == len(set(live)) and all(i >= 0 for i in live)
        fid = r.index_data["files"]["a.py"]["symbols"][0]["faiss_id"]
        assert r.faiss_index.reconstruct(int(fid)).shape == (384,)

    def test_same_file_changed_by_both_the_local_change_wins(self, seeded):
        tmp = seeded
        a, _ = _mk(); a.load()
        b, _ = _mk(); b.load()
        _write(tmp, "base.py", "base_v_b"); b.index_file("base.py"); b.save()
        _write(tmp, "base.py", "base_v_a"); a.index_file("base.py"); a.save()
        r, _ = _mk(); r.load()
        assert r.lookup_symbol("base_v_a") and not r.lookup_symbol("base_v_b")
        _assert_consistent(r)
        # the replaced file's old vectors are gone, not left live
        assert r.faiss_index.ntotal == len({s["faiss_id"] for f in r.index_data["files"].values()
                                            for s in f["symbols"]}) + 1   # + the file summary

    def test_removal_by_the_stale_writer_is_applied_to_the_newer_state(self, seeded):
        tmp = seeded
        _write(tmp, "b.py", "from_b")
        a, _ = _mk(); a.load()
        b, _ = _mk(); b.load(); b.index_file("b.py"); b.save()
        a.index_data["files"].pop("base.py")
        a.note_file_removed("base.py")
        a.save()
        r, _ = _mk(); r.load()
        assert sorted(r.index_data["files"]) == ["b.py"]
        assert not r.lookup_symbol("base_fn") and r.lookup_symbol("from_b")
        _assert_consistent(r)

    def test_no_rebase_when_nobody_else_wrote(self, seeded, monkeypatch):
        a, _ = _mk(); a.load()
        called = []
        monkeypatch.setattr(type(a), "_rebase_onto_disk_locked", lambda self: called.append(1))
        _write(seeded, "a.py", "from_a")
        a.index_file("a.py"); a.save()
        assert called == []
        a.index_file("a.py"); a.save()                  # own write adopted as the baseline
        assert called == []

    def test_dirty_set_is_cleared_after_save_and_load(self, seeded):
        a, _ = _mk(); a.load()
        _write(seeded, "a.py", "from_a")
        a.index_file("a.py")
        assert a._dirty() == {"a.py": "set"}  # pylint: disable=protected-access
        a.save()
        assert a._dirty() == {}  # pylint: disable=protected-access

    def test_reload_if_changed_keeps_unsaved_local_edits(self, seeded):
        tmp = seeded
        _write(tmp, "a.py", "from_a")
        _write(tmp, "b.py", "from_b")
        a, _ = _mk(); a.load(); a.index_file("a.py")           # unsaved
        b, _ = _mk(); b.load(); b.index_file("b.py"); b.save()
        assert a.reload_if_changed() is True
        assert a.lookup_symbol("from_b") and a.lookup_symbol("from_a")   # both visible, none lost
        a.save()
        r, _ = _mk(); r.load()
        assert sorted(r.index_data["files"]) == ["a.py", "b.py", "base.py"]

    def test_fresh_indexer_that_never_loaded_still_overwrites(self, seeded):
        """A from-scratch build (never synced) is not 'stale' — behaviour unchanged."""
        _write(seeded, "z.py", "zed")
        f, _ = _mk()
        f.index_file("z.py"); f.save()
        r, _ = _mk(); r.load()
        assert sorted(r.index_data["files"]) == ["z.py"]

    def test_no_embed_stale_writer(self, isolated_cognirepo, tmp_path):
        _write(tmp_path, "base.py", "base_fn")
        s, _ = _mk(embed=False); s.index_file("base.py"); s.save()
        _write(tmp_path, "a.py", "from_a"); _write(tmp_path, "b.py", "from_b")
        a, _ = _mk(embed=False); a.load()
        b, _ = _mk(embed=False); b.load(); b.index_file("b.py"); b.save()
        a.index_file("a.py"); a.save()
        r, _ = _mk(embed=False); r.load()
        assert sorted(r.index_data["files"]) == ["a.py", "b.py", "base.py"]


def test_two_real_processes(isolated_cognirepo, tmp_path):
    """The acceptance case from the issue, with real processes: a watcher holds an older copy,
    index-repo completes, the watcher's next event => the stores contain both."""
    _write(tmp_path, "base.py", "base_fn")
    _write(tmp_path, "from_b.py", "from_b")
    _write(tmp_path, "from_a.py", "from_a")
    s, sg = _mk(embed=False); s.index_file("base.py"); s.save(); sg.save()
    env = {**os.environ, "COGNIREPO_DIR": str(tmp_path / ".cognirepo"),
           "PYTHONPATH": os.pathsep.join(sys.path)}
    code = textwrap.dedent("""
        import sys, time, os
        from data.graph.knowledge_graph import KnowledgeGraph
        from intelligence.indexer.ast_indexer import ASTIndexer
        who, f = sys.argv[1], sys.argv[2]
        ix = ASTIndexer(graph=KnowledgeGraph()); ix._embed_enabled = False; ix.load()
        open(who + ".loaded", "w").close()
        while not os.path.exists(sys.argv[3]): time.sleep(0.02)
        ix.index_file(f); ix.save()
    """)
    go_a, go_b = tmp_path / "go_a", tmp_path / "go_b"
    pa = subprocess.Popen([sys.executable, "-c", code, "A", "from_a.py", str(go_a)], cwd=tmp_path, env=env)
    pb = subprocess.Popen([sys.executable, "-c", code, "B", "from_b.py", str(go_b)], cwd=tmp_path, env=env)
    import time
    for _ in range(300):
        if (tmp_path / "A.loaded").exists() and (tmp_path / "B.loaded").exists():
            break
        time.sleep(0.05)
    go_b.write_text("x"); assert pb.wait(timeout=120) == 0      # index-repo finishes first
    go_a.write_text("x"); assert pa.wait(timeout=120) == 0      # then the stale watcher saves
    r, _ = _mk(embed=False); r.load()
    assert sorted(r.index_data["files"]) == ["base.py", "from_a.py", "from_b.py"]
