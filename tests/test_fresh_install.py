# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Task 1.1 — rank_bm25 dependency declared.

Verifies that episodic_search works without ImportError on a fresh install
(i.e. rank_bm25 is a declared dependency, not an accidental transitive one).
"""
import importlib


def test_rank_bm25_importable():
    """rank_bm25 must be importable — it is a declared hard dependency."""
    mod = importlib.import_module("rank_bm25")
    assert hasattr(mod, "BM25Plus"), "rank_bm25.BM25Plus not found"


def test_episodic_search_no_import_error():
    """episodic_search must run without raising ImportError."""
    from memory.episodic_memory import search_episodes, log_event

    log_event("sprint1 test entry", {"tag": "test"})
    results = search_episodes("sprint1 test")
    # Should return a list (possibly empty on very fresh store, but no exception)
    assert isinstance(results, list)
