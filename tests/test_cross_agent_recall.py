# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Tests for cross-agent persistent learning recall.

Simulates: Claude session stores a correction → session ends →
Gemini session starts → retrieve_learnings returns the correction.
"""
import pytest

from memory.learning_store import CompositeLearningStore


def test_cross_agent_correction_recall(tmp_path, monkeypatch):
    """
    Learning stored by 'Claude' session must be retrievable by a
    'Gemini' session using the same shared FAISS / project store.
    """
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / "global"))

    # ── Claude session ────────────────────────────────────────────────────────
    claude_store = CompositeLearningStore(project_dir=str(tmp_path / "proj"))
    claude_store.store_learning(
        "correction",
        "Fixed: used synchronous db call, corrected to async. Always use await session.execute().",
        metadata={"source_model": "claude-sonnet-4-6", "session_id": "session-claude-001"},
        scope="project",
    )

    # ── Gemini session (new CompositeLearningStore instance — same files) ─────
    gemini_store = CompositeLearningStore(project_dir=str(tmp_path / "proj"))
    results = gemini_store.retrieve_learnings(
        "database async",
        top_k=5,
        types=["correction", "prod_issue"],
    )

    assert len(results) >= 1
    texts = " ".join(r.get("text", "") for r in results)
    assert "async" in texts.lower() or "synchronous" in texts.lower()


def test_retrieve_learnings_filtered_by_type(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / "global"))
    store = CompositeLearningStore(project_dir=str(tmp_path / "proj"))

    store.store_learning("correction", "Fixed: wrong jwt expiry", {}, scope="project")
    store.store_learning("decision", "We decided to use Redis", {}, scope="project")
    store.store_learning("prod_issue", "Prod issue: auth was slow", {}, scope="project")

    corrections = store.retrieve_learnings("", types=["correction"])
    assert all(r["type"] == "correction" for r in corrections)

    prod_issues = store.retrieve_learnings("", types=["prod_issue"])
    assert all(r["type"] == "prod_issue" for r in prod_issues)
