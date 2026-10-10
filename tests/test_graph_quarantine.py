# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Quarantined graph files: recoverable vs locked vs corrupt, restore, retention (COGNIREPO-118).

Three `graph.pkl.corrupt-*` files on a dev machine were intact Fernet ciphertext (41,327 / 1,122 / 2
nodes) that pre-#97 code had quarantined when `keyring` was missing. They must be restorable, and
retention must only ever touch files that genuinely fail to decrypt AND unpickle.
"""
import json
import os
import pickle
import time
from unittest import mock

import networkx as nx
import pytest

from data.graph import quarantine as gq


def _graph(n):
    g = nx.DiGraph()
    for i in range(n):
        g.add_node(f"n{i}")
        if i:
            g.add_edge(f"n{i - 1}", f"n{i}")
    return g


def _gdir():
    d = os.path.join(".cognirepo", "graph")
    os.makedirs(d, exist_ok=True)
    return d


def _put(name, data: bytes):
    p = os.path.abspath(os.path.join(_gdir(), name))
    with open(p, "wb") as fh:
        fh.write(data)
    return p


def _plain(n):
    return pickle.dumps(_graph(n))


@pytest.fixture
def encrypted(isolated_cognirepo):
    pytest.importorskip("cryptography")
    pytest.importorskip("keyring")
    with open(".cognirepo/config.json", "w", encoding="utf-8") as f:
        json.dump({"project_id": "q-enc", "storage": {"encrypt": True}}, f)
    store: dict = {}
    with mock.patch("keyring.get_password", side_effect=lambda s, p: store.get(p)), \
         mock.patch("keyring.set_password", side_effect=lambda s, p, v: store.__setitem__(p, v)):
        yield


def _encrypt(data: bytes) -> bytes:
    from core.security.encryption import encrypt_bytes, get_or_create_key
    return encrypt_bytes(data, get_or_create_key("q-enc"))


class TestInspect:
    def test_plain_pickle_is_recoverable_with_counts(self, isolated_cognirepo):
        q = gq.inspect(_put("graph.pkl.corrupt-1700000000", _plain(5)))
        assert (q.status, q.nodes, q.edges, q.ts) == ("recoverable", 5, 4, 1700000000)

    def test_a_missing_file_is_reported_not_raised(self, isolated_cognirepo):
        q = gq.inspect(os.path.abspath(os.path.join(_gdir(), "graph.pkl")))
        assert q.status == "corrupt" and "unreadable" in q.reason

    def test_garbage_is_corrupt(self, isolated_cognirepo):
        q = gq.inspect(_put("graph.pkl.corrupt-1700000001", b"\x00not a pickle at all"))
        assert q.status == "corrupt" and q.reason

    def test_a_pickle_of_something_else_is_corrupt(self, isolated_cognirepo):
        q = gq.inspect(_put("graph.pkl.corrupt-1700000002", pickle.dumps({"not": "a graph"})))
        assert q.status == "corrupt"

    def test_encrypted_graph_is_recoverable_with_the_right_key(self, encrypted):
        q = gq.inspect(_put("graph.pkl.corrupt-1700000003", _encrypt(_plain(7))))
        assert (q.status, q.nodes) == ("recoverable", 7)

    def test_ciphertext_that_cannot_be_decrypted_is_locked_not_corrupt(self, encrypted):
        other = mock.patch("core.security.encryption.decrypt_bytes", side_effect=RuntimeError("no keyring"))
        blob = _encrypt(_plain(3))
        with other:
            q = gq.inspect(_put("graph.pkl.corrupt-1700000004", blob))
        assert q.status == "locked" and "no keyring" in q.reason

    def test_ciphertext_with_encryption_off_is_locked(self, isolated_cognirepo):
        q = gq.inspect(_put("graph.pkl.corrupt-1700000005", b"gAAAAABfake-ciphertext"))
        assert q.status == "locked"


class TestListAndBest:
    def test_listing_is_newest_first_and_ignores_other_files(self, isolated_cognirepo):
        _put("graph.pkl.corrupt-100", _plain(1))
        _put("graph.pkl.corrupt-300", _plain(1))
        _put("graph.pkl.corrupt-200", _plain(1))
        _put("graph.pkl", _plain(1))
        _put("graph.pkl.replaced-5", _plain(1))
        assert [q.ts for q in gq.list_quarantined()] == [300, 200, 100]

    def test_the_largest_graph_wins_not_the_newest(self, isolated_cognirepo):
        """41,327 -> 1,122 -> 2 nodes: later quarantines are usually tiny graphs that replaced the big one."""
        _put("graph.pkl.corrupt-100", _plain(50))
        _put("graph.pkl.corrupt-200", _plain(10))
        _put("graph.pkl.corrupt-300", _plain(2))
        _put("graph.pkl.corrupt-400", b"junk")
        assert gq.best_candidate(gq.list_quarantined()).ts == 100

    def test_none_when_nothing_recoverable(self, isolated_cognirepo):
        _put("graph.pkl.corrupt-100", b"junk")
        assert gq.best_candidate(gq.list_quarantined()) is None


class TestRestore:
    def test_dry_run_changes_nothing(self, isolated_cognirepo):
        _put("graph.pkl.corrupt-100", _plain(20))
        outcome, chosen, _ = gq.restore(apply=False)
        assert outcome == "dry-run" and chosen.nodes == 20
        assert not os.path.exists(os.path.join(_gdir(), "graph.pkl"))

    def test_restore_copies_the_best_and_keeps_the_quarantine(self, isolated_cognirepo):
        _put("graph.pkl.corrupt-100", _plain(20))
        _put("graph.pkl.corrupt-200", _plain(2))
        outcome, chosen, _ = gq.restore(apply=True)
        assert outcome == "restored" and chosen.nodes == 20
        from data.graph.knowledge_graph import KnowledgeGraph
        assert KnowledgeGraph().G.number_of_nodes() == 20          # the real loader reads it
        assert os.path.exists(os.path.join(_gdir(), "graph.pkl.corrupt-100"))   # nothing deleted

    def test_encrypted_quarantine_restores_and_loads(self, encrypted):
        _put("graph.pkl.corrupt-100", _encrypt(_plain(30)))
        assert gq.restore(apply=True)[0] == "restored"
        from data.graph.knowledge_graph import KnowledgeGraph
        assert KnowledgeGraph().G.number_of_nodes() == 30

    def test_a_readable_graph_is_not_replaced_without_force(self, isolated_cognirepo):
        live = _put("graph.pkl", _plain(5))
        _put("graph.pkl.corrupt-100", _plain(50))
        outcome, _, msg = gq.restore(apply=True)
        assert outcome == "graph-present" and "--force" in msg
        assert pickle.loads(open(live, "rb").read()).number_of_nodes() == 5

    def test_force_replaces_it_and_keeps_the_old_one(self, isolated_cognirepo):
        _put("graph.pkl", _plain(5))
        _put("graph.pkl.corrupt-100", _plain(50))
        assert gq.restore(apply=True, force=True)[0] == "restored"
        names = os.listdir(_gdir())
        assert any(n.startswith("graph.pkl.replaced-") for n in names)
        from data.graph.knowledge_graph import KnowledgeGraph
        assert KnowledgeGraph().G.number_of_nodes() == 50

    def test_an_unreadable_graph_pkl_is_replaced_without_force(self, isolated_cognirepo):
        _put("graph.pkl", b"truncated garbage")
        _put("graph.pkl.corrupt-100", _plain(9))
        assert gq.restore(apply=True)[0] == "restored"

    def test_nothing_and_nothing_recoverable(self, isolated_cognirepo):
        assert gq.restore(apply=True)[0] == "nothing"
        _put("graph.pkl.corrupt-100", b"junk")
        assert gq.restore(apply=True)[0] == "none-recoverable"


class TestRetention:
    def test_only_old_corrupt_files_are_removed(self, isolated_cognirepo):
        now = time.time()
        old, new = int(now - 90 * 86400), int(now - 2 * 86400)
        bad_old = _put(f"graph.pkl.corrupt-{old}", b"junk")
        bad_new = _put(f"graph.pkl.corrupt-{new}", b"junk")
        good_old = _put(f"graph.pkl.corrupt-{old - 1}", _plain(10))          # recoverable AND old
        locked_old = _put(f"graph.pkl.corrupt-{old - 2}", b"gAAAAAfake")     # locked AND old
        eligible, removed = gq.prune_corrupt(days=30, apply=True, now=now)
        assert [q.path for q in eligible] == [bad_old] and [q.path for q in removed] == [bad_old]
        assert not os.path.exists(bad_old)
        for keep in (bad_new, good_old, locked_old):
            assert os.path.exists(keep), keep

    def test_dry_run_removes_nothing(self, isolated_cognirepo):
        now = time.time()
        p = _put(f"graph.pkl.corrupt-{int(now - 90 * 86400)}", b"junk")
        eligible, removed = gq.prune_corrupt(days=30, apply=False, now=now)
        assert len(eligible) == 1 and removed == [] and os.path.exists(p)


class TestCli:
    def test_restore_dry_run_then_apply(self, isolated_cognirepo, capsys):
        from interface.cli.main import _cmd_graph_restore
        _put("graph.pkl.corrupt-100", _plain(12))
        assert _cmd_graph_restore(apply=False) == 0
        out = capsys.readouterr().out
        assert "[recoverable]" in out and "Dry run" in out and "12 nodes" in out
        assert _cmd_graph_restore(apply=True) == 0
        assert os.path.exists(os.path.join(_gdir(), "graph.pkl"))

    def test_prune_cli_reports_what_it_keeps(self, isolated_cognirepo, capsys):
        from interface.cli.main import _cmd_graph_prune_quarantine
        _put("graph.pkl.corrupt-100", _plain(3))
        assert _cmd_graph_prune_quarantine(30, apply=True) == 0
        out = capsys.readouterr().out
        assert "keeping 1 file(s)" in out and os.path.exists(os.path.join(_gdir(), "graph.pkl.corrupt-100"))

    def test_doctor_offers_restore_when_graph_pkl_is_missing(self, isolated_cognirepo, capsys):
        from interface.cli.main import _cmd_doctor
        _put("graph.pkl.corrupt-100", _plain(8))
        _put("graph.pkl.corrupt-200", b"junk")
        _cmd_doctor(verbose=False)
        out = capsys.readouterr().out
        assert "RECOVERABLE" in out and "graph restore --apply" in out
        assert "genuinely unreadable" in out and "prune-quarantine" in out

    def test_doctor_does_not_push_a_restore_over_a_healthy_graph(self, isolated_cognirepo, capsys):
        """A readable graph.pkl + an older, bigger quarantine: informative at most, never a warning."""
        from interface.cli.main import _cmd_doctor
        _put("graph.pkl", _plain(5))
        _put("graph.pkl.corrupt-100", _plain(500))
        _cmd_doctor(verbose=False)
        out = capsys.readouterr().out
        assert "RECOVERABLE" not in out and "--force" not in out
        _cmd_doctor(verbose=True)
        assert "graph.pkl is healthy" in capsys.readouterr().out
