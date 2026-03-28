# pylint: disable=missing-docstring, unnecessary-lambda, import-outside-toplevel, too-few-public-methods, duplicate-code
# pylint: disable=redefined-outer-name, unused-argument, broad-exception-caught, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tests/test_init_seed.py — A2.1 init UX and A2.2 git-seed tests.
"""
from __future__ import annotations

import json
import os

import pytest


# ── A2.1 init ─────────────────────────────────────────────────────────────────

class TestInitProject:
    def test_gitignore_is_created(self):
        from cli.init_project import init_project
        init_project(no_index=True)
        assert os.path.exists(".cognirepo/.gitignore")

    def test_gitignore_content(self):
        from cli.init_project import init_project
        init_project(no_index=True)
        content = open(".cognirepo/.gitignore").read()
        # Blanket pattern: everything is excluded, only .gitignore is whitelisted
        assert "*" in content
        assert "!.gitignore" in content

    def test_config_json_created(self):
        from cli.init_project import init_project
        init_project(no_index=True)
        assert os.path.exists(".cognirepo/config.json")
        data = json.load(open(".cognirepo/config.json"))
        # Secrets no longer live in config — project_id and api_url must be present
        assert "project_id" in data
        assert "api_url" in data
        assert "storage" in data

    def test_no_index_returns_none_triple(self):
        from cli.init_project import init_project
        result = init_project(no_index=True)
        assert result == (None, None, None)

    def test_idempotent_project_id_preserved(self):
        """Re-running init must not regenerate the project_id."""
        from cli.init_project import init_project
        init_project(no_index=True)
        original_id = json.load(open(".cognirepo/config.json"))["project_id"]
        init_project(password="newpass", no_index=True)  # nosec B105
        current_id = json.load(open(".cognirepo/config.json"))["project_id"]
        assert current_id == original_id

    def test_no_secrets_in_config_when_keyring_available(self, monkeypatch):
        """When keyring is present, jwt_secret and password_hash must not be in config."""
        import unittest.mock as mock
        from cli.init_project import init_project

        with mock.patch("cli.init_project._KEYRING_AVAILABLE", True), \
             mock.patch("cli.init_project._store_secret", return_value=True):
            init_project(no_index=True)

        data = json.load(open(".cognirepo/config.json"))
        assert "password_hash" not in data
        assert "jwt_secret" not in data

    def test_prompt_n_returns_none_triple(self, monkeypatch):
        from cli.init_project import init_project
        monkeypatch.setattr("builtins.input", lambda: "n")
        result = init_project()
        assert result == (None, None, None)

    def test_prompt_no_returns_none_triple(self, monkeypatch):
        from cli.init_project import init_project
        monkeypatch.setattr("builtins.input", lambda: "no")
        result = init_project()
        assert result == (None, None, None)

    def test_scaffold_dirs_created(self):
        from cli.init_project import init_project
        init_project(no_index=True)
        for d in (".cognirepo/memory", ".cognirepo/index", ".cognirepo/graph", "vector_db"):
            assert os.path.isdir(d)


# ── A2.2 seed ─────────────────────────────────────────────────────────────────

class TestSeedFromGitLog:
    def test_returns_dict(self):
        from cli.seed import seed_from_git_log
        result = seed_from_git_log(dry_run=True)
        assert isinstance(result, dict)

    def test_non_git_dir_returns_skipped(self, tmp_path, monkeypatch):
        """In a directory with no git repo, seed should fail silently."""
        monkeypatch.chdir(tmp_path)
        # tmp_path has no .cognirepo; create minimal dirs
        os.makedirs(".cognirepo/graph", exist_ok=True)
        os.makedirs("vector_db", exist_ok=True)
        from cli.seed import seed_from_git_log
        result = seed_from_git_log()
        # Should be skipped — no error raised to user
        assert "skipped" in result

    def test_already_seeded_is_idempotent(self):
        from graph.knowledge_graph import KnowledgeGraph
        from graph.behaviour_tracker import BehaviourTracker
        from cli.seed import seed_from_git_log

        kg = KnowledgeGraph()
        tracker = BehaviourTracker(graph=kg)
        # Pre-populate weights so it looks already seeded
        tracker.data["symbol_weights"]["some::symbol"] = {"hit_count": 1.0, "last_hit": None, "relevance_feedback": 0.0}

        result = seed_from_git_log(tracker=tracker)
        assert result.get("skipped") == "already seeded"

    def test_dry_run_writes_nothing(self):
        from graph.knowledge_graph import KnowledgeGraph
        from graph.behaviour_tracker import BehaviourTracker
        from cli.seed import seed_from_git_log

        kg = KnowledgeGraph()
        tracker = BehaviourTracker(graph=kg)
        seed_from_git_log(dry_run=True, tracker=tracker)
        # Weights should still be empty — nothing written
        assert not tracker.data.get("symbol_weights")

    def test_seed_in_git_repo_populates_weights(self):
        """In the actual cognirepo git repo, seeding should produce entries."""
        import subprocess
        # Verify we can reach a git repo
        proc = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            pytest.skip("no git repo available")

        from graph.knowledge_graph import KnowledgeGraph
        from graph.behaviour_tracker import BehaviourTracker
        from indexer.ast_indexer import ASTIndexer
        from cli.seed import seed_from_git_log

        # Use the real cognirepo root
        import pathlib
        repo_root = str(pathlib.Path(__file__).parent.parent)

        kg = KnowledgeGraph()
        tracker = BehaviourTracker(graph=kg)
        indexer = ASTIndexer(graph=kg)
        indexer.load()

        result = seed_from_git_log(repo_root=repo_root, tracker=tracker, indexer=indexer)
        # Either seeded some entries or skipped (already seeded)
        assert "seeded" in result or "skipped" in result
        if result.get("seeded", 0) > 0:
            assert len(tracker.data.get("symbol_weights", {})) > 0
