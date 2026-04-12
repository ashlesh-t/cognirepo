# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""Tests for server/learning_middleware.py — auto-learning intercepts."""
from server.learning_middleware import intercept_after_store, intercept_after_episode


def test_intercept_after_store_captures_correction(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / "global"))
    import memory.learning_store as ls
    # Reset singleton
    ls._STORE = None

    stored = []
    original_store = ls.CompositeLearningStore.store_learning

    def mock_store(self, learning_type, text, metadata=None, scope="auto"):
        stored.append({"type": learning_type, "text": text})
        return {"id": "test-id", "scope": "project"}

    monkeypatch.setattr(ls.CompositeLearningStore, "store_learning", mock_store)
    ls._STORE = ls.CompositeLearningStore(project_dir=str(tmp_path / "proj"))

    intercept_after_store("Fixed: used synchronous db call, corrected to async")

    assert len(stored) == 1
    assert stored[0]["type"] == "correction"


def test_intercept_after_store_ignores_normal_text(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / "global"))
    import memory.learning_store as ls
    ls._STORE = None

    stored = []

    def mock_store(self, *a, **kw):
        stored.append(a)
        return {"id": "x", "scope": "project"}

    monkeypatch.setattr(ls.CompositeLearningStore, "store_learning", mock_store)
    ls._STORE = ls.CompositeLearningStore(project_dir=str(tmp_path / "proj"))

    intercept_after_store("retrieved 5 memories for context")
    assert len(stored) == 0


def test_intercept_after_episode_captures_prod_issue(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / "global"))
    import memory.learning_store as ls
    ls._STORE = None

    stored = []

    def mock_store(self, learning_type, text, metadata=None, scope="auto"):
        stored.append(learning_type)
        return {"id": "eid", "scope": "project"}

    monkeypatch.setattr(ls.CompositeLearningStore, "store_learning", mock_store)
    ls._STORE = ls.CompositeLearningStore(project_dir=str(tmp_path / "proj"))

    intercept_after_episode("Prod issue reported: feature A race condition")

    assert len(stored) == 1
    assert stored[0] == "prod_issue"
