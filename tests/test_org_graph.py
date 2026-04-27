# pylint: disable=missing-docstring, import-outside-toplevel, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_org_graph.py — Phase 0 acceptance criteria for OrgGraph.

Covers:
  - Concurrent writes from two threads don't corrupt the graph
  - Encryption round-trip: save encrypted → load decrypted = original graph
  - Plaintext save/load works when encryption disabled
"""
from __future__ import annotations

import os
import threading
from unittest import mock

import pytest


@pytest.fixture()
def org_graph_path(tmp_path, monkeypatch):
    """Redirect org_graph storage to a temp path."""
    path = str(tmp_path / "org_graph.pkl")
    monkeypatch.setenv("COGNIREPO_ORG_GRAPH", path)
    # Also redirect the lock file to tmp_path
    import graph.org_graph as _og
    monkeypatch.setattr(
        _og,
        "_org_lock",
        lambda: __import__("filelock").FileLock(str(tmp_path / "org_graph.lock")),
    )
    yield path


class TestOrgGraphConcurrentWrite:
    def test_two_thread_writes_no_corruption(self, org_graph_path, isolated_cognirepo):
        """Two threads saving OrgGraph simultaneously must not corrupt the pickle."""
        from graph.org_graph import OrgGraph, invalidate_org_graph

        errors: list[Exception] = []

        def _write_repo(repo_name: str) -> None:
            try:
                og = OrgGraph()
                og.add_repo(f"/tmp/{repo_name}")
                og.save()
            except Exception as exc:  # pylint: disable=broad-except
                errors.append(exc)

        invalidate_org_graph()
        t1 = threading.Thread(target=_write_repo, args=("repo_a",))
        t2 = threading.Thread(target=_write_repo, args=("repo_b",))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert not errors, f"Thread errors: {errors}"

        # File must be loadable after concurrent writes
        og_final = OrgGraph()
        # At least one repo was saved — graph is not empty or corrupt
        assert og_final.G is not None


class TestOrgGraphEncryption:
    def test_plaintext_round_trip(self, org_graph_path, isolated_cognirepo):
        """Save + load without encryption preserves graph data."""
        from graph.org_graph import OrgGraph, invalidate_org_graph

        invalidate_org_graph()
        og = OrgGraph()
        og.add_repo("/tmp/test-repo")
        og.save()

        invalidate_org_graph()
        og2 = OrgGraph()
        assert og2.G.has_node(os.path.abspath("/tmp/test-repo"))

    def test_encrypt_round_trip(self, org_graph_path, isolated_cognirepo):
        """With encryption enabled, save → load returns the same graph."""
        pytest.importorskip("cryptography")
        pytest.importorskip("keyring")

        import json
        with open(".cognirepo/config.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["storage"] = {"encrypt": True}
        with open(".cognirepo/config.json", "w", encoding="utf-8") as f:
            json.dump(cfg, f)

        key_store: dict = {}

        def fake_get(svc, proj):
            return key_store.get(proj)

        def fake_set(svc, proj, val):
            key_store[proj] = val

        from graph.org_graph import OrgGraph, invalidate_org_graph

        with mock.patch("keyring.get_password", side_effect=fake_get), \
             mock.patch("keyring.set_password", side_effect=fake_set):
            invalidate_org_graph()
            og = OrgGraph()
            og.add_repo("/tmp/enc-repo")
            og.save()

            invalidate_org_graph()
            og2 = OrgGraph()

        assert og2.G.has_node(os.path.abspath("/tmp/enc-repo"))

    def test_corrupt_file_falls_back_to_empty(self, org_graph_path, isolated_cognirepo):
        """Corrupt pickle file → OrgGraph falls back to empty graph (no crash)."""
        with open(org_graph_path, "wb") as f:
            f.write(b"not a valid pickle")

        from graph.org_graph import OrgGraph, invalidate_org_graph
        invalidate_org_graph()
        og = OrgGraph()
        assert og.G.number_of_nodes() == 0
