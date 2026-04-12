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


# ── deprecate_learning ────────────────────────────────────────────────────────

def test_deprecate_hides_from_retrieve(tmp_path):
    store = ProjectLearningStore(project_dir=str(tmp_path))
    rid = store.store_learning("decision", "We decided to use sync db calls", {})
    assert store.retrieve_learnings("sync db", top_k=5)  # visible before deprecate

    found = store.deprecate_learning(rid)
    assert found is True
    results = store.retrieve_learnings("sync db", top_k=5)
    assert not any(r["id"] == rid for r in results), "Deprecated record must not appear"


def test_deprecate_unknown_id_returns_false(tmp_path):
    store = ProjectLearningStore(project_dir=str(tmp_path))
    assert store.deprecate_learning("nonexistent-id") is False


def test_deprecate_idempotent(tmp_path):
    store = ProjectLearningStore(project_dir=str(tmp_path))
    rid = store.store_learning("decision", "We decided to use async", {})
    store.deprecate_learning(rid)
    # second call should not raise, just return False (already deprecated)
    assert store.deprecate_learning(rid) is False


def test_composite_deprecate_finds_project_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / "global"))
    store = CompositeLearningStore(project_dir=str(tmp_path / "proj"))
    result = store.store_learning("decision", "We decided X", {}, scope="project")
    rid = result["id"]

    dep = store.deprecate_learning(rid)
    assert dep["found"] is True
    assert dep["scope"] == "project"
    assert not any(r["id"] == rid for r in store.retrieve_learnings("decided X"))


def test_composite_deprecate_finds_global_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / "global"))
    store = CompositeLearningStore(project_dir=str(tmp_path / "proj"))
    result = store.store_learning("decision", "Prefer composition globally", {}, scope="global")
    rid = result["id"]

    dep = store.deprecate_learning(rid)
    assert dep["found"] is True
    assert dep["scope"] == "global"


def test_composite_deprecate_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / "global"))
    store = CompositeLearningStore(project_dir=str(tmp_path / "proj"))
    dep = store.deprecate_learning("ghost-id")
    assert dep["found"] is False
    assert dep["scope"] is None


# ── supersede_learning ────────────────────────────────────────────────────────

def test_supersede_replaces_old_with_new(tmp_path):
    store = ProjectLearningStore(project_dir=str(tmp_path))
    old_id = store.store_learning("decision", "We decided to use sync db calls", {})

    result = store.supersede_learning(
        old_id=old_id,
        new_text="We decided to use async db calls",
        learning_type="decision",
    )
    assert result["found_old"] is True
    assert result["new_id"] != old_id

    all_results = store.retrieve_learnings("db calls", top_k=10)
    ids = [r["id"] for r in all_results]
    assert old_id not in ids, "Superseded record must not appear"
    assert result["new_id"] in ids, "Replacement record must appear"


def test_supersede_new_record_carries_supersedes_field(tmp_path):
    store = ProjectLearningStore(project_dir=str(tmp_path))
    old_id = store.store_learning("decision", "Use Redis for caching", {})

    result = store.supersede_learning(
        old_id=old_id,
        new_text="Use Memcached for caching",
        learning_type="decision",
    )
    new_results = store.retrieve_learnings("caching", top_k=5)
    new_record = next((r for r in new_results if r["id"] == result["new_id"]), None)
    assert new_record is not None
    assert new_record.get("supersedes") == old_id


def test_composite_supersede_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / "global"))
    store = CompositeLearningStore(project_dir=str(tmp_path / "proj"))

    old_result = store.store_learning("decision", "We decided to use sync db calls", {}, scope="project")
    old_id = old_result["id"]

    sup = store.supersede_learning(
        old_id=old_id,
        new_text="We decided to use async db calls",
        learning_type="decision",
        scope="project",
    )
    assert sup["found_old"] is True
    assert sup["new_id"] != old_id

    final = store.retrieve_learnings("db calls", top_k=10)
    ids = [r["id"] for r in final]
    assert old_id not in ids
    assert sup["new_id"] in ids


# ── detect_conflicts ──────────────────────────────────────────────────────────

def test_detect_conflicts_returns_similar_records(tmp_path):
    store = ProjectLearningStore(project_dir=str(tmp_path))
    store.store_learning("decision", "We decided to use sync db calls throughout the codebase", {})

    conflicts = store.detect_conflicts("We decided to use async db calls throughout the codebase")
    assert len(conflicts) >= 1, "Should flag the existing sync decision as a potential conflict"


def test_detect_conflicts_ignores_deprecated(tmp_path):
    store = ProjectLearningStore(project_dir=str(tmp_path))
    rid = store.store_learning("decision", "We decided to use sync db calls throughout", {})
    store.deprecate_learning(rid)

    conflicts = store.detect_conflicts("We decided to use async db calls throughout")
    assert all(c["id"] != rid for c in conflicts), "Deprecated records must not appear in conflicts"


def test_detect_conflicts_no_match_returns_empty(tmp_path):
    store = ProjectLearningStore(project_dir=str(tmp_path))
    store.store_learning("decision", "We use FAISS for vector search", {})

    conflicts = store.detect_conflicts("unrelated topic about CI pipelines and deployment")
    assert conflicts == []


def test_composite_detect_conflicts_merges_scopes(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / "global"))
    store = CompositeLearningStore(project_dir=str(tmp_path / "proj"))

    store.store_learning("decision", "We decided to use sync db calls throughout the repo", {}, scope="project")
    store.store_learning("decision", "Always use sync calls throughout global preference", {}, scope="global")

    conflicts = store.detect_conflicts("We decided to use async calls throughout")
    assert len(conflicts) >= 1
