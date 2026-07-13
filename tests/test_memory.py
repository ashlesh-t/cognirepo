# pylint: disable=missing-docstring, unnecessary-lambda, import-outside-toplevel, too-few-public-methods, duplicate-code
# pylint: disable=redefined-outer-name, unused-argument, broad-exception-caught, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_memory.py — semantic + episodic memory round-trip tests.
"""
from __future__ import annotations

import os


class TestSemanticMemory:
    def test_store_and_retrieve(self):
        from data.memory.semantic_memory import SemanticMemory
        sm = SemanticMemory()
        sm.store("the quick brown fox jumps over the lazy dog")
        results = sm.retrieve("fox jumps", top_k=1)
        assert len(results) >= 1
        assert "fox" in results[0]["text"].lower() or "quick" in results[0]["text"].lower()

    def test_importance_score_positive(self):
        from data.memory.semantic_memory import SemanticMemory
        sm = SemanticMemory()
        sm.store("fixed critical authentication bug in verify_token function")
        results = sm.retrieve("auth bug", top_k=1)
        assert results[0]["importance"] >= 0

    def test_multiple_store_retrieve(self):
        from data.memory.semantic_memory import SemanticMemory
        sm = SemanticMemory()
        texts = [
            "Python list comprehension syntax",
            "JWT token expiry handling in auth module",
            "Docker multi-stage build optimisation",
        ]
        for t in texts:
            sm.store(t)
        results = sm.retrieve("authentication JWT", top_k=2)
        assert len(results) >= 1
        # JWT-related memory should rank highest
        top_text = results[0]["text"].lower()
        assert "jwt" in top_text or "auth" in top_text

    def test_retrieve_top_k_respected(self):
        from data.memory.semantic_memory import SemanticMemory
        sm = SemanticMemory()
        for i in range(10):
            sm.store(f"memory item {i} about various topics and code")
        results = sm.retrieve("code topics", top_k=3)
        assert len(results) <= 3


class TestEpisodicMemory:
    def test_log_and_retrieve(self):
        from data.memory.episodic_memory import log_event, get_history
        log_event("user ran cognirepo init", {"status": "ok"})
        log_event("user stored memory about auth bug", {})
        history = get_history(limit=10)
        assert len(history) == 2
        assert "cognirepo init" in history[0]["event"] or "auth bug" in history[0]["event"]

    def test_history_order(self):
        from data.memory.episodic_memory import log_event, get_history
        log_event("first event", {})
        log_event("second event", {})
        log_event("third event", {})
        history = get_history(limit=10)
        # all 3 events should be present
        all_events = " ".join(h["event"] for h in history)
        assert "first" in all_events
        assert "second" in all_events
        assert "third" in all_events

    def test_history_limit(self):
        from data.memory.episodic_memory import log_event, get_history
        for i in range(10):
            log_event(f"event {i}", {})
        history = get_history(limit=3)
        assert len(history) == 3

    def test_event_has_required_fields(self):
        from data.memory.episodic_memory import log_event, get_history
        log_event("test event", {"key": "value"})
        ev = get_history(1)[0]
        assert "event" in ev
        assert "time" in ev or "timestamp" in ev

    def test_metadata_stored(self):
        from data.memory.episodic_memory import log_event, get_history
        log_event("deployed service", {"version": "1.2.3", "env": "prod"})
        ev = get_history(1)[0]
        meta = ev.get("metadata", {})
        assert meta.get("version") == "1.2.3"

    def test_ids_unique_after_rotation(self, tmp_path):
        import json
        from core.config.paths import get_path
        from data.memory.episodic_memory import log_event, _load, _archive_path

        cfg_path = get_path("config.json")
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["episodic_max_events"] = 20
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)

        for i in range(25):
            log_event(f"event {i}", {})

        live = _load()
        apath = _archive_path()
        archive = []
        if os.path.exists(apath):
            with open(apath, encoding="utf-8") as f:
                archive = json.load(f)

        all_ids = [e["id"] for e in live] + [e["id"] for e in archive]
        assert len(all_ids) == len(set(all_ids)), f"duplicate ids found: {all_ids}"

    def test_prev_chain_resolvable_after_rotation(self):
        import json
        from core.config.paths import get_path
        from data.memory.episodic_memory import log_event, _load, _archive_path

        cfg_path = get_path("config.json")
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["episodic_max_events"] = 10
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)

        for i in range(15):
            log_event(f"event {i}", {})

        live = _load()
        apath = _archive_path()
        archive = []
        if os.path.exists(apath):
            with open(apath, encoding="utf-8") as f:
                archive = json.load(f)

        id_set = {e["id"] for e in live} | {e["id"] for e in archive}
        for entry in live:
            if "prev" in entry:
                assert entry["prev"] in id_set

    def test_existing_store_ids_unchanged_on_load(self):
        from data.memory.episodic_memory import log_event, get_history

        log_event("first event", {})
        log_event("second event", {})
        before = [e["id"] for e in get_history(10)]
        # loading again must not rewrite existing IDs
        after = [e["id"] for e in get_history(10)]
        assert before == after
