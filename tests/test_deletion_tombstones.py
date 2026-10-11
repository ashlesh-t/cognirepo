# pylint: disable=missing-docstring, import-outside-toplevel, protected-access, redefined-outer-name, unused-argument
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""COGNIREPO-169: a file deleted in a commit is hidden at once and purged after a grace window."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time

import numpy as np
import pytest

from tests.test_incremental_persist import indexed_repo, _run_cli, no_model  # noqa: F401


def _state(repo):
    from data.graph.knowledge_graph import KnowledgeGraph
    from intelligence.indexer.ast_indexer import ASTIndexer
    kg = KnowledgeGraph()
    ix = ASTIndexer(graph=kg)
    ix.load()
    return ix, kg


def _delete(repo, monkeypatch, name="b.py"):
    os.remove(repo / name)
    monkeypatch.chdir(repo)
    _run_cli(monkeypatch, "index-repo", "--files", name, "--no-watch", "--no-embed")


def _set_grace(repo, secs):
    cfg = repo / ".cognirepo" / "config.json"
    data = json.loads(cfg.read_text()) if cfg.exists() else {}
    data.setdefault("indexing", {})["delete_grace_secs"] = secs
    cfg.write_text(json.dumps(data))


def test_deleted_file_is_hidden_immediately_but_not_yet_purged(indexed_repo, monkeypatch):
    monkeypatch.chdir(indexed_repo)
    ix, _ = _state(indexed_repo)
    assert ix.lookup_symbol("caller")
    _delete(indexed_repo, monkeypatch)
    ix, kg = _state(indexed_repo)
    assert "b.py" in ix.index_data["files"]          # still on disk in the index: purge is later
    assert ix.lookup_symbol("caller") == []          # ...but never served
    assert ix.lookup_symbol("existing")              # untouched files still answer


def test_expired_tombstone_is_purged_everywhere(indexed_repo, monkeypatch):
    _set_grace(indexed_repo, 0)
    _delete(indexed_repo, monkeypatch)               # grace 0: marked and purged in one run
    ix, kg = _state(indexed_repo)
    assert "b.py" not in ix.index_data["files"]
    assert "caller" not in ix.index_data["reverse_index"]
    assert not [n for n in kg.G.nodes if str(n).startswith("b.py")]
    from intelligence.indexer import tombstones
    assert tombstones.load() == {}


def test_purge_happens_on_a_later_run_after_the_window(indexed_repo, monkeypatch):
    monkeypatch.chdir(indexed_repo)
    _delete(indexed_repo, monkeypatch)
    from intelligence.indexer import tombstones
    with open(tombstones._path(), "w", encoding="utf-8") as f:   # pretend: deleted an hour ago
        json.dump({"b.py": time.time() - 3600}, f)
    _run_cli(monkeypatch, "index-repo", "--files", "a.py", "--no-watch", "--no-embed")
    ix, kg = _state(indexed_repo)
    assert "b.py" not in ix.index_data["files"]
    assert tombstones.load() == {}


def test_recreate_inside_window_clears_tombstone(indexed_repo, monkeypatch):
    _delete(indexed_repo, monkeypatch)
    (indexed_repo / "b.py").write_text("def caller():\n    return 2\n")
    _run_cli(monkeypatch, "index-repo", "--files", "b.py", "--no-watch", "--no-embed")
    from intelligence.indexer import tombstones
    assert tombstones.load() == {}
    ix, _ = _state(indexed_repo)
    assert [loc["file"] for loc in ix.lookup_symbol("caller")] == ["b.py"]


def test_recreated_unchanged_file_is_visible_again(indexed_repo, monkeypatch):
    """Delete then restore identical content (git checkout): sha matches, tombstone must still go."""
    body = (indexed_repo / "b.py").read_text()
    _delete(indexed_repo, monkeypatch)
    (indexed_repo / "b.py").write_text(body)
    _run_cli(monkeypatch, "index-repo", "--files", "b.py", "--no-watch", "--no-embed")
    ix, _ = _state(indexed_repo)
    assert ix.lookup_symbol("caller")


def test_who_calls_skips_tombstoned_caller(indexed_repo, monkeypatch):
    monkeypatch.chdir(indexed_repo)
    _delete(indexed_repo, monkeypatch)
    from interface.server import mcp_server
    out = mcp_server.who_calls("existing")
    files = {c.get("file") for c in out.get("local_callers", [])}
    assert "b.py" not in files


def test_vector_hits_skip_tombstoned_file(isolated_cognirepo, tmp_path, monkeypatch):
    from data.graph.knowledge_graph import KnowledgeGraph
    from intelligence.indexer.ast_indexer import ASTIndexer
    from intelligence.indexer import tombstones
    from intelligence.retrieval.hybrid import HybridRetriever

    class FakeModel:
        def embed(self, texts):
            for t in texts:
                seed = int(hashlib.sha256(t.encode()).hexdigest()[:8], 16)
                yield np.random.default_rng(seed).random(384).astype("float32")

    monkeypatch.chdir(tmp_path)
    (tmp_path / "gone.py").write_text("def vanish():\n    return 1\n")
    ix = ASTIndexer(graph=KnowledgeGraph())
    ix.model = FakeModel()
    ix.index_file("gone.py")
    q = np.random.rand(384).astype("float32")
    r = HybridRetriever.__new__(HybridRetriever)
    r.indexer = ix
    assert r._ast_faiss_retrieve(q, 5)
    tombstones.mark(["gone.py"])
    assert r._ast_faiss_retrieve(q, 5) == []


def test_remove_file_drops_vectors_graph_and_record(isolated_cognirepo, tmp_path, monkeypatch):
    from data.graph.knowledge_graph import KnowledgeGraph
    from intelligence.indexer.ast_indexer import ASTIndexer
    from tests.test_ast_index_rebase import FakeModel
    monkeypatch.chdir(tmp_path)
    (tmp_path / "k.py").write_text("def kept():\n    return 1\n")
    (tmp_path / "g.py").write_text("def gone_fn():\n    return 1\n")
    ix = ASTIndexer(graph=KnowledgeGraph())
    ix.model = FakeModel()
    ix.index_file("k.py")
    ix.index_file("g.py")
    before = ix.faiss_index.ntotal
    assert ix.remove_file("g.py") == {"gone_fn"}
    assert "g.py" not in ix.index_data["files"]
    assert ix.faiss_index.ntotal < before
    assert not [n for n in ix.graph.G.nodes if str(n).startswith("g.py")]
    assert any(str(n).startswith("k.py") for n in ix.graph.G.nodes)


def test_full_index_leaves_no_tombstone_for_a_deleted_file(indexed_repo, monkeypatch):
    _delete(indexed_repo, monkeypatch)
    _run_cli(monkeypatch, "index-repo", str(indexed_repo), "--no-watch", "--no-embed")
    ix, kg = _state(indexed_repo)
    from intelligence.indexer import tombstones
    assert "b.py" not in ix.index_data["files"]
    assert tombstones.load() == {}
