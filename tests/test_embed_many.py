# Copyright (c) 2026 Ashlesh T. — AGPL-3.0 (see LICENSE)
"""Bulk embedding is bounded (#98, #105): small batches, input order kept, breaker consulted, configurable."""
from __future__ import annotations

import json

import numpy as np
import pytest

from data.memory import embeddings as emb
from data.memory.circuit_breaker import CircuitOpenError


class FakeModel:
    """Records every call; the vector for a text is [len(text), ord(first char)] so order is checkable."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def embed(self, texts, batch_size=256, **_):
        texts = list(texts)
        self.calls.append(texts)
        assert len(texts) <= batch_size
        for t in texts:
            yield np.array([len(t), ord(t[0])], dtype="float64")


class TestEmbedMany:
    def test_batches_are_bounded_and_the_result_is_in_input_order(self):
        texts = [("x" * (n % 37 + 1)) + str(n % 10) for n in range(100)]
        model = FakeModel()
        out = emb.embed_many(model, texts, batch_size=8)
        assert out.shape == (100, 2) and out.dtype == np.float32
        assert all(len(c) <= 8 for c in model.calls) and len(model.calls) == 13
        assert [int(v[0]) for v in out] == [len(t) for t in texts]          # row i belongs to texts[i]

    def test_texts_are_embedded_shortest_first(self):
        model = FakeModel()
        emb.embed_many(model, ["ccc", "a", "bb", "dddd", "e"], batch_size=2)
        lengths = [len(t) for call in model.calls for t in call]
        assert lengths == sorted(lengths)

    def test_empty_input_has_the_embedding_width(self):
        assert emb.embed_many(FakeModel(), []).shape == (0, emb.EMBED_DIM)

    def test_progress_counts_every_text(self):
        seen = []
        emb.embed_many(FakeModel(), ["a"] * 21, batch_size=5, progress=seen.append)
        assert sum(seen) == 21 and max(seen) == 5

    def test_the_breaker_is_checked_before_every_batch_and_can_stop_the_run(self, monkeypatch):
        checks = []

        class Breaker:
            def check(self):
                checks.append(1)
                if len(checks) == 3:
                    raise CircuitOpenError("rss over the limit")
        import data.memory.circuit_breaker as cb
        monkeypatch.setattr(cb, "get_breaker", lambda: Breaker())
        model = FakeModel()
        with pytest.raises(CircuitOpenError):
            emb.embed_many(model, ["t"] * 50, batch_size=5)
        assert len(model.calls) == 2, "the third batch must never reach the model"

    def test_batch_size_never_exceeds_the_cap(self):
        model = FakeModel()
        emb.embed_many(model, ["t"] * 600, batch_size=10_000)
        assert max(len(c) for c in model.calls) == emb.MAX_EMBED_BATCH


class TestBatchSizeSetting:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("COGNIREPO_EMBED_BATCH", raising=False)
        assert emb.embed_batch_size() == emb.DEFAULT_EMBED_BATCH == 16

    def test_env_wins_over_config(self, monkeypatch, isolated_cognirepo):
        from core.config.paths import get_path
        with open(get_path("config.json"), "w", encoding="utf-8") as fh:
            json.dump({"embedding": {"batch_size": 64}}, fh)
        monkeypatch.delenv("COGNIREPO_EMBED_BATCH", raising=False)
        assert emb.embed_batch_size() == 64
        monkeypatch.setenv("COGNIREPO_EMBED_BATCH", "8")
        assert emb.embed_batch_size() == 8

    @pytest.mark.parametrize("raw,want", [("0", 1), ("-5", 1), ("100000", 256), ("abc", 16), ("", 16)])
    def test_clamped_and_garbage_falls_back(self, monkeypatch, raw, want):
        monkeypatch.setenv("COGNIREPO_EMBED_BATCH", raw)
        assert emb.embed_batch_size() == want


class TestCallSites:
    def test_the_indexers_bulk_embed_never_sends_a_big_batch(self, monkeypatch, isolated_cognirepo):
        """The pre-fix code called model.embed(all_texts) with fastembed's default batch of 256 (5 GB on celery)."""
        monkeypatch.delenv("COGNIREPO_EMBED_BATCH", raising=False)
        from intelligence.indexer.ast_indexer import ASTIndexer
        idx = ASTIndexer.__new__(ASTIndexer)
        idx.model = FakeModel()
        idx.faiss_meta = []

        class Index:
            def add_with_ids(self, *_a):
                pass
        idx.faiss_index = Index()
        idx._pending_embeds = [(f"symbol {i}", {"name": str(i)}, {}) for i in range(300)]
        idx._batch_embed_pending()
        assert idx.model.calls and max(len(c) for c in idx.model.calls) <= emb.DEFAULT_EMBED_BATCH
        assert len(idx.faiss_meta) == 300 and not idx._pending_embeds


class TestPartialFailureKeepsWhatWasDone:
    def _indexer(self, model, n):
        from intelligence.indexer.ast_indexer import ASTIndexer
        idx = ASTIndexer.__new__(ASTIndexer)
        idx.model, idx.faiss_meta = model, []

        class Index:
            def __init__(self):
                self.ids = []

            def add_with_ids(self, _v, ids):
                self.ids.extend(int(i) for i in ids)
        idx.faiss_index = Index()
        idx._pending_embeds = [(f"symbol {i}", {"name": str(i)}, {"n": i}) for i in range(n)]
        return idx

    def test_a_breaker_trip_part_way_keeps_the_embedded_windows_and_says_so(self, monkeypatch, capsys):
        import data.memory.circuit_breaker as cb
        calls = {"n": 0}

        class Breaker:
            def check(self):
                calls["n"] += 1
                if calls["n"] > 40:                     # 32 batches of 16 = the first 512-text window, then trip
                    raise CircuitOpenError("rss over the limit")
        monkeypatch.setattr(cb, "get_breaker", lambda: Breaker())
        idx = self._indexer(FakeModel(), 1000)
        idx._batch_embed_pending()
        out = capsys.readouterr().out
        assert "Embedding stopped after 512 of 1,000 symbols" in out and "without vectors" in out
        assert len(idx.faiss_meta) == 512 and len(idx.faiss_index.ids) == 512     # the finished window survived
        assert len(idx._pending_embeds) == 488, "the rest stay queued for a later flush"

    def test_a_clean_run_clears_the_queue(self):
        idx = self._indexer(FakeModel(), 700)
        idx._batch_embed_pending()
        assert not idx._pending_embeds and len(idx.faiss_meta) == 700
