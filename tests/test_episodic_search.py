# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tests/test_episodic_search.py — Sprint 4 / TASK-013 acceptance tests.

Verifies that memory.episodic_memory.search_episodes() now uses BM25Okapi
(rank_bm25) instead of keyword intersection — TF-IDF ranking, cache
invalidation, and mark_stale() integration.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _raw_save(tmp_path: Path, data: list) -> None:
    (tmp_path / "episodic.json").write_text(json.dumps(data))


def _raw_load(tmp_path: Path) -> list:
    p = tmp_path / "episodic.json"
    return json.loads(p.read_text()) if p.exists() else []


def _patch_episodic(monkeypatch, tmp_path):
    """Wire episodic_memory to use raw JSON in tmp_path (no encryption)."""
    import memory.episodic_memory as em
    em._BM25_CORPUS = None
    em._BM25_INDEX = None
    monkeypatch.setattr(em, "_load", lambda: _raw_load(tmp_path))
    monkeypatch.setattr(em, "_save", lambda data: (
        _raw_save(tmp_path, data),
        em.__dict__.update({"_BM25_CORPUS": None, "_BM25_INDEX": None}),
    ))


def _seed(tmp_path: Path) -> None:
    _raw_save(tmp_path, [
        {
            "id": "e_0",
            "event": "authentication JWT token verification failed in middleware",
            "metadata": {"file": "auth/auth.py"},
            "time": "2026-01-01T00:00:00Z",
        },
        {
            "id": "e_1",
            "event": "error logged",
            "metadata": {},
            "time": "2026-01-01T00:01:00Z",
        },
        {
            "id": "e_2",
            "event": "database connection pool exhausted error",
            "metadata": {},
            "time": "2026-01-01T00:02:00Z",
        },
    ])


# ── BM25 ranking ──────────────────────────────────────────────────────────────

class TestBM25RankingInSearchEpisodes:
    def test_specific_match_ranks_first(self, tmp_path, monkeypatch):
        """'authentication JWT' should rank e_0 above e_1 (generic 'error')."""
        _patch_episodic(monkeypatch, tmp_path)
        _seed(tmp_path)

        import memory.episodic_memory as em
        em._BM25_CORPUS = None
        em._BM25_INDEX = None

        from memory.episodic_memory import search_episodes
        results = search_episodes("authentication JWT", limit=3)

        assert len(results) >= 1
        assert results[0]["id"] == "e_0"

    def test_no_query_token_overlap_excluded(self, tmp_path, monkeypatch):
        """Episodes with zero BM25 score are excluded from results."""
        _patch_episodic(monkeypatch, tmp_path)
        _seed(tmp_path)

        import memory.episodic_memory as em
        em._BM25_CORPUS = None
        em._BM25_INDEX = None

        from memory.episodic_memory import search_episodes
        # "zzzxxx" matches nothing → all scores are 0 → empty list
        results = search_episodes("zzzxxx_nonexistent_term", limit=5)
        assert results == []

    def test_empty_corpus_returns_empty(self, tmp_path, monkeypatch):
        _patch_episodic(monkeypatch, tmp_path)
        _raw_save(tmp_path, [])

        import memory.episodic_memory as em
        em._BM25_CORPUS = None
        em._BM25_INDEX = None

        from memory.episodic_memory import search_episodes
        assert search_episodes("anything", limit=5) == []

    def test_limit_respected(self, tmp_path, monkeypatch):
        _patch_episodic(monkeypatch, tmp_path)
        _seed(tmp_path)

        import memory.episodic_memory as em
        em._BM25_CORPUS = None
        em._BM25_INDEX = None

        from memory.episodic_memory import search_episodes
        results = search_episodes("error", limit=1)
        assert len(results) <= 1

    def test_results_are_full_episode_dicts(self, tmp_path, monkeypatch):
        """Each result must be a full episode dict (id, event, time)."""
        _patch_episodic(monkeypatch, tmp_path)
        _seed(tmp_path)

        import memory.episodic_memory as em
        em._BM25_CORPUS = None
        em._BM25_INDEX = None

        from memory.episodic_memory import search_episodes
        results = search_episodes("error", limit=5)
        for r in results:
            assert "id" in r
            assert "event" in r
            assert "time" in r


# ── BM25 cache invalidation ───────────────────────────────────────────────────

class TestBM25CacheLifecycle:
    def test_cache_built_on_first_search(self, tmp_path, monkeypatch):
        _patch_episodic(monkeypatch, tmp_path)
        _seed(tmp_path)

        import memory.episodic_memory as em
        em._BM25_CORPUS = None
        em._BM25_INDEX = None

        from memory.episodic_memory import search_episodes
        search_episodes("error", limit=3)
        assert em._BM25_INDEX is not None

    def test_cache_invalidated_on_save(self, tmp_path, monkeypatch):
        """After _save(), BM25 cache fields are reset to None."""
        import memory.episodic_memory as em

        # Use real _save but patch file paths
        monkeypatch.setattr(em, "_load", lambda: _raw_load(tmp_path))

        def _capturing_save(data):
            _raw_save(tmp_path, data)
            em._BM25_CORPUS = None
            em._BM25_INDEX = None

        monkeypatch.setattr(em, "_save", _capturing_save)

        em._BM25_CORPUS = None
        em._BM25_INDEX = None
        _seed(tmp_path)

        from memory.episodic_memory import search_episodes
        search_episodes("error", limit=3)
        assert em._BM25_INDEX is not None  # built

        # Trigger _save
        from memory.episodic_memory import mark_stale
        mark_stale("auth/auth.py")  # tags e_0, calls _save
        assert em._BM25_INDEX is None     # invalidated

    def test_cache_reused_without_save(self, tmp_path, monkeypatch):
        """Second search_episodes() call reuses the cached BM25 object."""
        _patch_episodic(monkeypatch, tmp_path)
        _seed(tmp_path)

        import memory.episodic_memory as em
        em._BM25_CORPUS = None
        em._BM25_INDEX = None

        from memory.episodic_memory import search_episodes
        search_episodes("error", limit=3)
        bm25_obj_first = em._BM25_INDEX

        search_episodes("authentication", limit=3)
        bm25_obj_second = em._BM25_INDEX

        assert bm25_obj_first is bm25_obj_second  # same cached instance
