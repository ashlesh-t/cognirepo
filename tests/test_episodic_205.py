# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_episodic_205.py — COGNIREPO-205 acceptance criteria.

1. search_episodes(include_archived=...) — archived events are searchable only
   with the flag; default behavior (live-only) is unchanged.
2. Persistent embedding cache for the semantic fallback — repeat searches over
   an unchanged corpus re-encode 0 documents (only the query, if anything).
3. index-repo logs exactly one index_event episode on a fixture repo.
4. datetime.utcnow() deprecation removed from episodic_memory.py.
"""
from __future__ import annotations

import json


# ── AC1: archive search ─────────────────────────────────────────────────────

class TestArchiveSearch:
    def test_archived_hit_found_only_with_flag(self, tmp_path, monkeypatch):
        import data.memory.episodic_memory as em
        em._BM25_CORPUS = None
        em._BM25_INDEX = None

        # live store: nothing matching
        (tmp_path / ".cognirepo" / "memory").mkdir(parents=True, exist_ok=True)
        live = [{"id": "e_1", "event": "reviewed PR", "metadata": {}, "time": "2026-08-01T00:00:00Z"}]
        (tmp_path / ".cognirepo" / "memory" / "episodic.json").write_text(json.dumps(live))

        # archive: unique keyword
        archived = [{"id": "e_0", "event": "zanzibar migration notes", "metadata": {}, "time": "2026-07-01T00:00:00Z"}]
        (tmp_path / ".cognirepo" / "memory" / "episodic_archive.json").write_text(json.dumps(archived))

        from data.memory.episodic_memory import search_episodes

        without_flag = search_episodes("zanzibar", limit=5, include_archived=False)
        assert without_flag == []

        with_flag = search_episodes("zanzibar", limit=5, include_archived=True)
        by_id = {r["id"]: r for r in with_flag}
        assert "e_0" in by_id, "archived entry must be findable with include_archived=True"
        assert by_id["e_0"]["archived"] is True

    def test_live_hit_not_marked_archived(self, tmp_path, monkeypatch):
        import data.memory.episodic_memory as em
        em._BM25_CORPUS = None
        em._BM25_INDEX = None

        (tmp_path / ".cognirepo" / "memory").mkdir(parents=True, exist_ok=True)
        live = [{"id": "e_1", "event": "zanzibar deployed to prod", "metadata": {}, "time": "2026-08-01T00:00:00Z"}]
        (tmp_path / ".cognirepo" / "memory" / "episodic.json").write_text(json.dumps(live))
        archived = [{"id": "e_0", "event": "zanzibar migration notes", "metadata": {}, "time": "2026-07-01T00:00:00Z"}]
        (tmp_path / ".cognirepo" / "memory" / "episodic_archive.json").write_text(json.dumps(archived))

        from data.memory.episodic_memory import search_episodes
        results = search_episodes("zanzibar", limit=5, include_archived=True)
        ids = {r["id"] for r in results}
        assert ids == {"e_0", "e_1"}
        live_result = next(r for r in results if r["id"] == "e_1")
        assert "archived" not in live_result

    def test_default_excludes_archive(self, tmp_path, monkeypatch):
        """include_archived defaults to False — matches TC-205-1's expectation."""
        import data.memory.episodic_memory as em
        em._BM25_CORPUS = None
        em._BM25_INDEX = None

        (tmp_path / ".cognirepo" / "memory").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".cognirepo" / "memory" / "episodic.json").write_text(json.dumps([]))
        archived = [{"id": "e_0", "event": "zanzibar migration notes", "metadata": {}, "time": "2026-07-01T00:00:00Z"}]
        (tmp_path / ".cognirepo" / "memory" / "episodic_archive.json").write_text(json.dumps(archived))

        from data.memory.episodic_memory import search_episodes
        assert search_episodes("zanzibar", limit=5) == []


# ── AC2: persistent embedding cache ──────────────────────────────────────────

class TestSemanticSearchEmbeddingCache:
    def test_second_identical_search_reencodes_no_entries(self, tmp_path, monkeypatch):
        import numpy as np
        import data.memory.episodic_memory as em

        entries = [
            {"id": f"e_{i}", "event": f"unique topic phrase number {i}", "metadata": {}, "time": "2026-08-01T00:00:00Z"}
            for i in range(5)
        ]

        calls = {"n": 0}
        rng = np.random.default_rng(42)
        vec_by_text: dict[str, "np.ndarray"] = {}

        def _fake_encode(text, timeout=None):
            calls["n"] += 1
            if text not in vec_by_text:
                vec_by_text[text] = rng.random(8).astype("float32")
            return vec_by_text[text]

        monkeypatch.setattr("data.memory.embeddings.encode_with_timeout", _fake_encode)

        # BM25 returns nothing for this query -> forces the semantic fallback
        query = "zzz_no_bm25_overlap_zzz"

        first = em._semantic_episode_search(entries, query, limit=5)
        calls_after_first = calls["n"]
        assert calls_after_first == len(entries) + 1  # 5 entries + 1 query

        calls["n"] = 0
        second = em._semantic_episode_search(entries, query, limit=5)
        # Only the query needs encoding again — all 5 entries now cache hits.
        assert calls["n"] == 1

    def test_embedding_cache_written_to_disk_and_reloadable(self, tmp_path, monkeypatch):
        """Cache file + id sidecar are written under .cognirepo/memory/ and reloadable."""
        import numpy as np
        import data.memory.episodic_memory as em

        entries = [{"id": "e_0", "event": "solo cached entry", "metadata": {}, "time": "2026-08-01T00:00:00Z"}]

        def _fake_encode(text, timeout=None):
            return np.ones(8, dtype="float32")

        monkeypatch.setattr("data.memory.embeddings.encode_with_timeout", _fake_encode)
        em._semantic_episode_search(entries, "anything", limit=5)

        ids, vecs = em._load_vec_cache()
        assert ids == ["e_0"]
        assert vecs.shape == (1, 8)


# ── AC3: system events land in the timeline ──────────────────────────────────

class TestIndexEventLogging:
    def test_index_repo_logs_exactly_one_index_event(self, tmp_path, monkeypatch):
        from core.config.paths import set_cognirepo_dir
        set_cognirepo_dir(str(tmp_path / ".cognirepo"))
        monkeypatch.chdir(tmp_path)
        (tmp_path / "hello.py").write_text("def greet(name):\n    return name\n")

        from interface.cli.main import _direct_index
        _direct_index(str(tmp_path), embed=False, skip_graph=True)

        from data.memory.episodic_memory import get_history
        index_events = [
            e for e in get_history(limit=1000)
            if e.get("metadata", {}).get("type") == "index_event"
        ]
        assert len(index_events) == 1
        assert "symbols" in index_events[0]["metadata"]
        assert "files" in index_events[0]["metadata"]


# ── AC4: datetime.utcnow() removed ───────────────────────────────────────────

class TestNoDeprecatedUtcnow:
    def test_log_event_timestamp_is_tz_aware_parseable(self, tmp_path, monkeypatch):
        from core.config.paths import set_cognirepo_dir
        set_cognirepo_dir(str(tmp_path / ".cognirepo"))

        import data.memory.episodic_memory as em
        em._BM25_CORPUS = None
        em._BM25_INDEX = None
        em.log_event("test event")

        from datetime import datetime
        data = em._load()
        assert len(data) == 1
        ts = data[0]["time"]
        # datetime.now(timezone.utc).isoformat() with "Z" suffix must parse cleanly
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None

    def test_no_utcnow_call_in_source(self):
        import inspect
        import data.memory.episodic_memory as em
        source = inspect.getsource(em)
        assert "datetime.utcnow()" not in source
