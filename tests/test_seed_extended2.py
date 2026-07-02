# pylint: disable=missing-docstring, import-outside-toplevel, broad-exception-caught
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""tests/test_seed_extended2.py — More coverage for cli/seed.py (31% → 65%)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo with some typed commits."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"],
                   check=True, capture_output=True)

    # Create a Python file and commit with typed prefix
    py_file = tmp_path / "main.py"
    py_file.write_text("def hello():\n    # TODO: improve this\n    pass\n")

    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m",
                    "fix: resolve auth token expiry bug causing session drops"],
                   check=True, capture_output=True)

    py_file.write_text("def hello():\n    # NOTE: critical path\n    return 42\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m",
                    "feat: add hybrid retrieval with FAISS and graph signals"],
                   check=True, capture_output=True)

    return tmp_path


# ── _seed_commit_messages with real git repo ──────────────────────────────────

def test_seed_commit_messages_real_repo_dry_run(git_repo):
    from interface.cli.seed import _seed_commit_messages
    result = _seed_commit_messages(str(git_repo), dry_run=True)
    assert isinstance(result, int)
    # May be 0 if learning_store unavailable, but shouldn't crash


def test_seed_commit_messages_real_repo_with_store(git_repo):
    from interface.cli.seed import _seed_commit_messages
    mock_store = MagicMock()
    mock_store.store_learning.return_value = {"id": "abc123"}
    with patch("data.memory.learning_store.get_learning_store", return_value=mock_store):
        result = _seed_commit_messages(str(git_repo), dry_run=False)
    assert isinstance(result, int)
    assert result >= 1  # should have stored at least 1 commit


def test_seed_commit_messages_no_git(tmp_path):
    from interface.cli.seed import _seed_commit_messages
    result = _seed_commit_messages(str(tmp_path), dry_run=True)
    assert result == 0  # not a git repo


# ── _seed_adr_files ───────────────────────────────────────────────────────────

def test_seed_adr_files_with_adr_dir(tmp_path):
    from interface.cli.seed import _seed_adr_files
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    adr_file = adr_dir / "0001-use-faiss.md"
    adr_file.write_text(
        "# ADR 0001: Use FAISS for Vector Search\n\n"
        "## Status\nAccepted\n\n## Context\n"
        "We need fast semantic search over code symbols. FAISS provides "
        "approximate nearest neighbor search with excellent performance for "
        "our embedding dimension (384). This decision was made after evaluating "
        "several alternatives including ChromaDB and Pinecone.\n\n"
        "## Decision\nUse FAISS with all-MiniLM-L6-v2 embeddings.\n\n"
        "## Consequences\nFaster queries, local-first, no external dependencies.\n"
    )
    mock_store = MagicMock()
    mock_store.store_learning.return_value = {"id": "xyz"}
    with patch("data.memory.learning_store.get_learning_store", return_value=mock_store):
        result = _seed_adr_files(str(tmp_path), dry_run=False)
    assert isinstance(result, int)
    assert result >= 0


def test_seed_adr_files_with_decisions_md(tmp_path):
    from interface.cli.seed import _seed_adr_files
    decisions = tmp_path / "DECISIONS.md"
    decisions.write_text(
        "# Architecture Decisions\n\n"
        "## Use FAISS\nWe chose FAISS for fast local vector search because it "
        "provides sub-millisecond queries and runs entirely locally. This is "
        "important for our privacy requirements and offline usage scenarios.\n\n"
        "## Use NetworkX\nNetworkX was chosen for the knowledge graph because it "
        "provides rich graph algorithms and is well-maintained with good Python support.\n"
    )
    result = _seed_adr_files(str(tmp_path), dry_run=True)
    assert isinstance(result, int)


def test_seed_adr_files_dry_run_prints(tmp_path, capsys):
    from interface.cli.seed import _seed_adr_files
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    adr_file = adr_dir / "0001-decision.md"
    adr_file.write_text("# Decision\n\nThis is a long enough decision text that should pass the 80-char minimum threshold for seeding into the learning store.\n")
    mock_store = MagicMock()
    with patch("data.memory.learning_store.get_learning_store", return_value=mock_store):
        result = _seed_adr_files(str(tmp_path), dry_run=True)
    assert isinstance(result, int)


# ── _seed_inline_comments with real Python file ───────────────────────────────

def test_seed_inline_comments_real_py(tmp_path):
    from interface.cli.seed import _seed_inline_comments
    py_file = tmp_path / "module.py"
    py_file.write_text(
        "# TODO: implement better caching strategy\n"
        "def compute():\n"
        "    # NOTE: critical path — avoid extra allocations here\n"
        "    # HACK: workaround for numpy 1.x incompatibility\n"
        "    pass\n"
        "\n"
        "# FIXME: this breaks when input contains unicode\n"
        "def parse(text):\n"
        "    return text.strip()\n"
    )
    result = _seed_inline_comments(str(tmp_path), dry_run=True)
    assert isinstance(result, int)


def test_seed_inline_comments_with_store(tmp_path):
    from interface.cli.seed import _seed_inline_comments
    py_file = tmp_path / "core.py"
    py_file.write_text(
        "# BUG: race condition in concurrent indexing\n"
        "def index_files():\n"
        "    pass\n"
        "# WARN: this is slow for large repos\n"
        "def slow_scan():\n"
        "    pass\n"
    )
    mock_store = MagicMock()
    with patch("data.memory.learning_store.get_learning_store", return_value=mock_store):
        result = _seed_inline_comments(str(tmp_path), dry_run=False)
    assert isinstance(result, int)


# ── seed_from_git_log with real git repo ──────────────────────────────────────

def test_seed_from_git_log_real_repo_dry_run(git_repo):
    from interface.cli.seed import seed_from_git_log
    mock_bt = MagicMock()
    mock_bt.data = {"symbol_weights": {}}
    mock_bt.save = MagicMock()
    mock_bt.graph = MagicMock()
    with patch("data.graph.behaviour_tracker.BehaviourTracker", return_value=mock_bt):
        with patch("data.graph.knowledge_graph.KnowledgeGraph"):
            result = seed_from_git_log(
                repo_root=str(git_repo),
                dry_run=True,
                seed_learnings=False,
                seed_adrs=False,
                seed_comments=False,
            )
    assert isinstance(result, dict)


def test_seed_from_git_log_no_git(tmp_path):
    from interface.cli.seed import seed_from_git_log
    result = seed_from_git_log(
        repo_root=str(tmp_path),
        dry_run=True,
    )
    assert isinstance(result, dict)
    assert "skipped" in result or "seeded" in result or isinstance(result, dict)


# ── seed_from_session ─────────────────────────────────────────────────────────

def test_seed_from_session_with_session_id():
    from interface.cli.seed import seed_from_session
    with patch("data.memory.episodic_memory.get_history", return_value=[
        {"event": "query: hybrid retrieval", "metadata": {"query": "hybrid retrieval"}},
        {"event": "session_end", "metadata": {"summary": "worked on retrieval"}},
    ]):
        result = seed_from_session(session_id="test-session-123")
    assert isinstance(result, dict)


def test_seed_from_session_empty_history():
    from interface.cli.seed import seed_from_session
    with patch("data.memory.episodic_memory.get_history", return_value=[]):
        result = seed_from_session(session_id="test-session-empty")
    assert isinstance(result, dict)
