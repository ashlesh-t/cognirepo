# pylint: disable=missing-docstring, import-outside-toplevel, too-few-public-methods, protected-access
# pylint: disable=redefined-outer-name, unused-argument, duplicate-code
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_graph_journal.py — incremental knowledge-graph journal (COGNIREPO-109).
"""
from __future__ import annotations

import json
import os
import random
from unittest import mock

import pytest

from data.graph.knowledge_graph import GraphLockedError, KnowledgeGraph, NodeType, EdgeType


def _graph_state(kg: KnowledgeGraph):
    nodes = {n: dict(d) for n, d in kg.G.nodes(data=True)}
    edges = {(u, v): dict(d) for u, v, d in kg.G.edges(data=True)}
    return nodes, edges


def _journal_path() -> str:
    from data.graph.knowledge_graph import _journal_file
    return _journal_file()


def _populate(kg: KnowledgeGraph, files: int = 5, flush_each: bool = False) -> None:
    for i in range(files):
        f = f"pkg/mod{i}.py"
        kg.add_node(f, NodeType.FILE, weight=1.0)
        for j in range(3):
            sym = f"{f}::fn{j}"
            kg.add_node(sym, NodeType.FUNCTION, file=f, line=j)
            kg.add_edge(sym, f, EdgeType.DEFINED_IN)
            if j:
                kg.add_edge(sym, f"{f}::fn{j - 1}", EdgeType.CALLED_BY, weight=0.5)
        if flush_each:
            kg.flush_journal()


@pytest.fixture
def encrypted(isolated_cognirepo):
    pytest.importorskip("cryptography")
    pytest.importorskip("keyring")
    cfg = {"project_id": "journal-enc", "storage": {"encrypt": True}}
    with open(".cognirepo/config.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    store: dict = {}
    with mock.patch("keyring.get_password", side_effect=lambda s, p: store.get(p)), \
         mock.patch("keyring.set_password", side_effect=lambda s, p, v: store.__setitem__(p, v)):
        yield


class TestReplay:
    def test_unsaved_journal_is_replayed_on_load(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        kg.begin_journal(flush_ops=10_000)
        _populate(kg)
        kg.end_journal()
        assert not os.path.exists(os.path.join(".cognirepo", "graph", "graph.pkl"))

        fresh = KnowledgeGraph()
        assert _graph_state(fresh) == _graph_state(kg)

    def test_replay_equivalence_random_ops(self, isolated_cognirepo):
        rng = random.Random(7)
        kg = KnowledgeGraph()
        kg.begin_journal(flush_ops=17)
        ids = [f"n{i}" for i in range(40)]
        for _ in range(600):
            op = rng.choice(["n", "n", "e", "e", "rn", "re", "na", "ea"])
            a, b = rng.choice(ids), rng.choice(ids)
            if op == "n":
                kg.add_node(a, NodeType.FUNCTION, v=rng.random())
            elif op == "e" and a != b:
                kg.add_node(a, NodeType.FUNCTION)
                kg.add_node(b, NodeType.FUNCTION)
                kg.add_edge(a, b, EdgeType.CALLED_BY, weight=rng.random())
            elif op == "rn":
                kg.remove_node(a)
            elif op == "re":
                kg.remove_edge(a, b)
            elif op == "na":
                kg.set_node_attrs(a, tag=rng.randint(0, 9))
            elif op == "ea":
                kg.set_edge_attrs(a, b, tag=rng.randint(0, 9))
            kg.maybe_flush()
        kg.end_journal()
        assert _graph_state(KnowledgeGraph()) == _graph_state(kg)

    def test_remove_file_nodes_and_stub_redirect_are_journaled(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        kg.begin_journal()
        _populate(kg, files=2)
        kg.add_node("other.py::caller", NodeType.FUNCTION, file="other.py")
        kg.add_edge("other.py::caller", "pkg/mod0.py::fn1", EdgeType.CALLED_BY, weight=0.9)
        kg.remove_file_nodes("pkg/mod0.py")
        kg.end_journal()
        fresh = KnowledgeGraph()
        assert _graph_state(fresh) == _graph_state(kg)
        assert fresh.G.has_node("symbol::fn1")  # stub kept the caller's edge

    def test_legacy_edge_without_rel_or_weight_round_trips(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        kg.G.add_node("m.py", type=NodeType.FILE)
        kg.G.add_node("m.py::f", type=NodeType.FUNCTION, file="m.py")
        kg.G.add_node("o.py::c", type=NodeType.FUNCTION, file="o.py")
        kg.G.add_edge("o.py::c", "m.py::f", custom=1)  # no rel, no weight
        kg.save()
        kg.begin_journal()
        kg.remove_file_nodes("m.py")  # redirects the legacy edge onto symbol::f
        kg.end_journal()
        assert "weight" not in kg.G["o.py::c"]["symbol::f"]
        assert _graph_state(KnowledgeGraph()) == _graph_state(kg)


class TestCompaction:
    def test_save_compacts_and_removes_journal(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        kg.begin_journal()
        _populate(kg)
        kg.flush_journal()
        assert os.path.exists(_journal_path())
        kg.save()
        assert not os.path.exists(_journal_path())
        assert _graph_state(KnowledgeGraph()) == _graph_state(kg)

    def test_crash_between_replace_and_unlink_does_not_double_apply(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        kg.begin_journal()
        _populate(kg, files=3)
        kg.flush_journal()
        kg.remove_node("pkg/mod1.py")
        kg.add_node("pkg/mod1.py", NodeType.FILE, weight=2.0)
        kg.flush_journal()
        with mock.patch.object(KnowledgeGraph, "_compact_journal_locked", lambda self: None):
            kg.save()
        assert os.path.exists(_journal_path())  # simulated crash: journal survived
        fresh = KnowledgeGraph()
        assert _graph_state(fresh) == _graph_state(kg)

    def test_save_failure_keeps_journal_and_nothing_is_lost(self, isolated_cognirepo):
        from data.memory.circuit_breaker import get_breaker
        kg = KnowledgeGraph()
        kg.begin_journal()
        _populate(kg)
        kg.end_journal()
        with mock.patch.object(get_breaker(), "check", side_effect=RuntimeError("tripped")):
            with pytest.raises(RuntimeError):
                kg.save()
        assert os.path.exists(_journal_path())
        assert _graph_state(KnowledgeGraph()) == _graph_state(kg)

    def test_pending_unflushed_ops_survive_in_save(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        kg.begin_journal(flush_ops=10_000)
        _populate(kg)  # never flushed
        kg.save()
        assert _graph_state(KnowledgeGraph()) == _graph_state(kg)

    def test_journal_after_compaction_continues_with_higher_seq(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        kg.begin_journal()
        _populate(kg, files=2)
        kg.flush_journal()
        kg.save()
        kg.add_node("late.py", NodeType.FILE)
        kg.end_journal()
        fresh = KnowledgeGraph()
        assert fresh.G.has_node("late.py")
        assert _graph_state(fresh) == _graph_state(kg)


class TestCrashRecovery:
    def test_torn_tail_loses_only_last_segment(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        kg.begin_journal()
        _populate(kg, files=3, flush_each=True)  # 3 segments
        path = _journal_path()
        size = os.path.getsize(path)
        with open(path, "r+b") as f:
            f.truncate(size - 5)  # tear the last record
        fresh = KnowledgeGraph()
        assert fresh.G.has_node("pkg/mod0.py") and fresh.G.has_node("pkg/mod1.py")
        assert not fresh.G.has_node("pkg/mod2.py")
        # reading must not have modified the file (reader may race a writer)
        assert os.path.getsize(path) == size - 5

    def test_writer_truncates_torn_tail_before_appending(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        kg.begin_journal()
        _populate(kg, files=2, flush_each=True)
        path = _journal_path()
        with open(path, "ab") as f:
            f.write(b"\x00\x00\x01\x00garbage")  # half-written record
        resumed = KnowledgeGraph()
        resumed.begin_journal()
        resumed.add_node("after.py", NodeType.FILE)
        resumed.end_journal()
        final = KnowledgeGraph()
        assert final.G.has_node("pkg/mod1.py") and final.G.has_node("after.py")

    def test_kill_mid_index_retains_flushed_segments(self, isolated_cognirepo, tmp_path):
        from intelligence.indexer.ast_indexer import ASTIndexer
        repo = tmp_path / "proj"
        repo.mkdir()
        for i in range(6):
            (repo / f"m{i}.py").write_text(f"def f{i}():\n    return {i}\n")
        (isolated_cognirepo / ".cognirepo" / "config.json").write_text(json.dumps(
            {"indexing": {"graph_journal_flush_files": 1, "graph_journal_flush_secs": 0}}))
        kg = KnowledgeGraph()
        indexer = ASTIndexer(graph=kg)
        real = ASTIndexer.index_file
        calls = {"n": 0}

        def dying(self, *a, **kw):
            calls["n"] += 1
            if calls["n"] == 5:
                raise KeyboardInterrupt  # not caught by the loops' `except Exception`
            return real(self, *a, **kw)

        with mock.patch.object(ASTIndexer, "index_file", dying):
            with pytest.raises(KeyboardInterrupt):
                indexer.index_repo(str(repo), embed=False)
        recovered = KnowledgeGraph()
        files = [n for n, d in recovered.G.nodes(data=True) if d.get("type") == NodeType.FILE]
        assert len(files) >= 3  # everything flushed before the interrupt survived
        assert os.path.exists(_journal_path())


class TestEncryption:
    def test_journal_is_ciphertext_and_round_trips(self, encrypted):
        kg = KnowledgeGraph()
        kg.begin_journal()
        kg.add_node("secret_module.py", NodeType.FILE)
        kg.end_journal()
        with open(_journal_path(), "rb") as f:
            assert b"secret_module" not in f.read()
        assert KnowledgeGraph().G.has_node("secret_module.py")
        kg.save()
        assert not os.path.exists(_journal_path())
        assert KnowledgeGraph().G.has_node("secret_module.py")

    def test_undecryptable_journal_is_preserved_and_blocks_save(self, encrypted):
        kg = KnowledgeGraph()
        kg.begin_journal()
        kg.add_node("x.py", NodeType.FILE)
        kg.end_journal()
        before = open(_journal_path(), "rb").read()
        with mock.patch("core.security.encryption.decrypt_bytes", side_effect=ValueError("bad key")):
            with pytest.warns(UserWarning, match="could not be read"):
                locked = KnowledgeGraph()
            with pytest.raises(GraphLockedError):
                locked.save()
        assert open(_journal_path(), "rb").read() == before


class TestReloadAndBounds:
    def test_reload_if_changed_sees_journal_only_change(self, isolated_cognirepo):
        writer = KnowledgeGraph()
        reader = KnowledgeGraph()
        writer.begin_journal()
        writer.add_node("j.py", NodeType.FILE)
        writer.flush_journal()
        assert reader.reload_if_changed() is True
        assert reader.G.has_node("j.py")
        assert reader.reload_if_changed() is False

    def test_journal_disabled_by_default_outside_indexing(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        kg.add_node("a", NodeType.FILE)
        assert kg._pending == [] and not os.path.exists(_journal_path())

    def test_flush_triggers_on_op_budget_and_segments_stay_bounded(self, isolated_cognirepo):
        from data.graph import journal
        kg = KnowledgeGraph()
        kg.begin_journal(flush_ops=100, flush_secs=3600)
        for i in range(2_000):
            kg.add_node(f"n{i}", NodeType.FUNCTION, file="f.py")
            kg.maybe_flush()
        assert len(kg._pending) < 100  # never accumulates the whole run
        kg.end_journal()
        segments, _, _ = journal.scan(_journal_path(), None)
        assert len(segments) >= 20
        assert max(len(ops) for _seq, ops in segments) <= 100

    def test_flush_failure_disables_journal_without_raising(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        kg.begin_journal(flush_ops=1)
        with mock.patch("data.graph.journal.append_segment", side_effect=OSError("disk full")):
            with pytest.warns(UserWarning, match="journal flush failed"):
                kg.add_node("a", NodeType.FILE)  # op budget reached -> flush -> fails softly
        assert not kg._journal_active
        kg.add_node("b", NodeType.FILE)  # indexing carries on
        kg.save()
        assert KnowledgeGraph().G.has_node("b")


class TestReviewRegressions:
    def test_seq_keeps_rising_across_runs_after_compaction(self, isolated_cognirepo):
        run1 = KnowledgeGraph()
        run1.begin_journal()
        _populate(kg=run1, files=2, flush_each=True)  # seqs 1, 2
        run1.save()  # journal removed, marker = 2
        run2 = KnowledgeGraph()  # no journal file on disk
        run2.begin_journal()
        run2.add_node("run2.py", NodeType.FILE)
        run2.end_journal()  # must be seq 3, not 1 — and the run dies before save()
        assert KnowledgeGraph().G.has_node("run2.py")

    def test_mid_file_corruption_is_not_treated_as_torn_tail(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        kg.begin_journal()
        _populate(kg, files=3, flush_each=True)
        path = _journal_path()
        raw = bytearray(open(path, "rb").read())
        raw[12] ^= 0xFF  # flip a byte inside the FIRST record's payload
        open(path, "wb").write(bytes(raw))
        before = bytes(raw)
        with pytest.warns(UserWarning, match="could not be read"):
            locked = KnowledgeGraph()
        assert locked._locked
        with pytest.raises(GraphLockedError):
            locked.save()
        assert open(path, "rb").read() == before  # nothing truncated

    def test_reload_clears_stale_lock_and_stale_graph(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        kg.begin_journal()
        kg.add_node("a.py", NodeType.FILE)
        kg.end_journal()
        path = _journal_path()
        good = open(path, "rb").read()
        bad = bytearray(good)
        bad[10] ^= 0xFF
        open(path, "wb").write(bytes(bad) + b"x")  # damage with trailing data
        with pytest.warns(UserWarning):
            reader = KnowledgeGraph()
        assert reader._locked
        open(path, "wb").write(good)  # repaired
        reader.load()
        assert not reader._locked and reader.G.has_node("a.py")

    def test_reader_replays_only_new_segments_incrementally(self, isolated_cognirepo):
        writer = KnowledgeGraph()
        writer.begin_journal()
        writer.add_node("one.py", NodeType.FILE)
        writer.flush_journal()
        reader = KnowledgeGraph()
        with mock.patch.object(KnowledgeGraph, "_load_base", side_effect=AssertionError("full reload")):
            writer.add_node("two.py", NodeType.FILE)
            writer.flush_journal()
            assert reader.reload_if_changed() is True
        assert reader.G.has_node("one.py") and reader.G.has_node("two.py")

    def test_op_count_flushes_inside_mutation_not_only_between_files(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        kg.begin_journal(flush_ops=50, flush_secs=3600)
        for i in range(500):
            kg.add_node(f"n{i}", NodeType.FUNCTION)  # no maybe_flush() calls at all
        assert len(kg._pending) < 50
        kg.end_journal()
        assert len(KnowledgeGraph().G) == 500

    def test_failed_end_journal_does_not_wedge_reload(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        kg.begin_journal(flush_ops=10_000)
        kg.add_node("x", NodeType.FILE)
        with mock.patch("data.graph.journal.append_segment", side_effect=OSError("full")):
            with pytest.raises(OSError):
                kg.end_journal()
        assert not kg._journal_active and kg._pending == []


_WRITER = """
import sys
sys.path.insert(0, {repo!r})
from core.config.paths import set_cognirepo_dir
set_cognirepo_dir({cdir!r})
from data.graph.knowledge_graph import KnowledgeGraph, NodeType
kg = KnowledgeGraph()
kg.begin_journal(flush_ops=10_000)
for i in range({segments}):
    for j in range(20):
        kg.add_node(f"seg{{i}}::n{{j}}", NodeType.FUNCTION, seg=i)
    kg.flush_journal()
kg.end_journal()
"""


class TestReviewRound2:
    def test_two_process_writer_reader_race(self, isolated_cognirepo):
        """A reader polling reload_if_changed() while another PROCESS appends segments
        must only ever see whole segments, never an error or a torn state."""
        import subprocess
        import sys
        import time
        segments = 40
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        code = _WRITER.format(repo=repo, cdir=str(isolated_cognirepo / ".cognirepo"),
                              segments=segments)
        reader = KnowledgeGraph()
        proc = subprocess.Popen([sys.executable, "-c", code])  # pylint: disable=consider-using-with
        try:
            deadline = time.time() + 60
            while proc.poll() is None and time.time() < deadline:
                reader.reload_if_changed()
                n = reader.G.number_of_nodes()
                assert n % 20 == 0, f"reader observed a partial segment ({n} nodes)"
            assert proc.wait(timeout=30) == 0
        finally:
            if proc.poll() is None:
                proc.kill()
        reader.reload_if_changed()
        assert reader.G.number_of_nodes() == segments * 20
        assert not reader._locked

    def test_replay_streams_one_segment_at_a_time(self, isolated_cognirepo):
        """Pin the bounded-memory claim: iterating the journal never holds more than
        ~one segment, however many segments exist (reviewer asked for a memory assertion)."""
        import tracemalloc
        from data.graph import journal
        kg = KnowledgeGraph()
        kg.begin_journal(flush_ops=10**9, flush_bytes=10**12)
        for seg in range(30):
            for j in range(2_000):
                kg.add_node(f"s{seg}::n{j}", NodeType.FUNCTION, file="f.py", blob="x" * 50)
            kg.flush_journal()
        kg.end_journal()
        path = _journal_path()

        def peak_of(consume) -> int:
            tracemalloc.start()
            try:
                consume()
                return tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()

        one = peak_of(lambda: next(journal.iter_segments(path, None)))
        streamed = peak_of(lambda: [None for _ in journal.iter_segments(path, None)])
        materialised = peak_of(lambda: journal.scan(path, None))
        assert streamed < one * 3          # constant in the number of segments
        assert materialised > streamed * 8  # the old list-based path scaled with the journal

    def test_boundary_scan_needs_no_key_and_no_unpickle(self, encrypted):
        from data.graph import journal
        kg = KnowledgeGraph()
        kg.begin_journal()
        _populate(kg, files=3, flush_each=True)
        kg.end_journal()
        path = _journal_path()
        size = os.path.getsize(path)
        with open(path, "ab") as f:
            f.write(b"\x00\x00\x10\x00torn")
        with mock.patch("core.security.encryption.decrypt_bytes", side_effect=AssertionError("decrypted")), \
             mock.patch("pickle.loads", side_effect=AssertionError("unpickled")):
            good_end, total = journal.boundary_end(path)
        assert good_end == size and total > size
        resumed = KnowledgeGraph()
        resumed.begin_journal()  # truncates the torn tail without decrypting
        assert os.path.getsize(path) == size

    def test_pending_is_bounded_by_estimated_bytes(self, isolated_cognirepo):
        kg = KnowledgeGraph()
        kg.begin_journal(flush_ops=10**9, flush_secs=3600, flush_bytes=20_000)
        for i in range(200):
            # few ops, but each carries a large attr list (e.g. ambiguous-stub candidates)
            kg.add_node(f"n{i}", NodeType.CONCEPT, candidates=[f"f{k}.py" for k in range(100)])
            assert kg._pending_cost < 20_000 + 10_000  # never runs away
        kg.end_journal()
        assert len(KnowledgeGraph().G) == 200

    def test_plaintext_segment_still_readable_under_encrypt(self, encrypted):
        """Journal written while encrypt resolved to false must still replay (mirrors graph.pkl)."""
        from data.graph import journal
        journal.append_segment(_journal_path(), 1, [("n", "plain.py", NodeType.FILE, {})], None)
        assert KnowledgeGraph().G.has_node("plain.py")
