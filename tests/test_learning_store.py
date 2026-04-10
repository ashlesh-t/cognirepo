# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""Tests for memory/learning_store.py — dual-scope learning store."""
import pytest

from memory.learning_store import (
    auto_tag,
    CompositeLearningStore,
    GlobalLearningStore,
    ProjectLearningStore,
)


# ── auto_tag ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected_type", [
    ("Fixed: used synchronous db call, corrected to async", "correction"),
    ("Mistake: wrong approach was used here", "correction"),
    ("Prod issue reported: feature A had race condition", "prod_issue"),
    ("Root cause was a missing lock in the scheduler", "prod_issue"),
    ("We decided to use async db calls throughout", "decision"),
    ("Decision: going with FAISS over ChromaDB", "decision"),
    ("Auth was slow on large responses", None),           # no signal
    ("updated the README", None),                         # no signal
])
def test_auto_tag_type(text, expected_type):
    learning_type, _ = auto_tag(text)
    assert learning_type == expected_type


def test_auto_tag_global_scope_for_ai_correction():
    _, scope = auto_tag("Correction: Claude misread intent — prefer composition over inheritance")
    assert scope == "global"


def test_auto_tag_project_scope_for_code_decision():
    _, scope = auto_tag("We decided to use async db calls in this repo")
    assert scope == "project"


def test_auto_tag_none_returns_none_none():
    t, s = auto_tag("some random text with no signal")
    assert t is None
    assert s is None


# ── ProjectLearningStore ──────────────────────────────────────────────────────

def test_project_store_round_trip(tmp_path):
    store = ProjectLearningStore(project_dir=str(tmp_path))
    rid = store.store_learning("correction", "Fixed: async call mistake", {})
    results = store.retrieve_learnings("async call", top_k=5)
    assert any(r["id"] == rid for r in results)


def test_project_store_filter_by_type(tmp_path):
    store = ProjectLearningStore(project_dir=str(tmp_path))
    store.store_learning("correction", "Fixed something", {})
    store.store_learning("decision", "We decided to use X", {})
    corrections = store.retrieve_learnings("", types=["correction"])
    assert all(r["type"] == "correction" for r in corrections)


# ── GlobalLearningStore ───────────────────────────────────────────────────────

def test_global_store_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path))
    store = GlobalLearningStore()
    rid = store.store_learning("decision", "Prefer composition", {})
    results = store.retrieve_learnings("composition", top_k=5)
    assert any(r["id"] == rid for r in results)


# ── CompositeLearningStore ────────────────────────────────────────────────────

def test_composite_merges_both_scopes(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / "global"))
    store = CompositeLearningStore(project_dir=str(tmp_path / "proj"))

    store.store_learning("correction", "Fixed: project mistake", {}, scope="project")
    store.store_learning("decision", "Global dev preference", {}, scope="global")

    results = store.retrieve_learnings("mistake preference", top_k=10)
    types_found = {r["type"] for r in results}
    assert "correction" in types_found
    assert "decision" in types_found


def test_composite_auto_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / "global"))
    store = CompositeLearningStore(project_dir=str(tmp_path / "proj"))
    # "correction" with no AI signal → project scope
    result = store.store_learning("correction", "Fixed: async db call mistake", scope="auto")
    assert result["scope"] in ("project", "global")  # auto-detected
    assert result["id"]


def test_composite_deduplication(tmp_path, monkeypatch):
    """Results from both scopes must not duplicate on the same ID."""
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / "global"))
    store = CompositeLearningStore(project_dir=str(tmp_path / "proj"))
    store.store_learning("decision", "We decided X", {}, scope="project")

    results = store.retrieve_learnings("we decided", top_k=10)
    ids = [r["id"] for r in results]
    assert len(ids) == len(set(ids)), "Duplicate IDs in results"
