# pylint: disable=missing-docstring, redefined-outer-name, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_insights_collector.py — COGNIREPO-301 acceptance criteria.

intelligence/orchestrator/insights_collector.py aggregates the merged timeline,
git history, behaviour hot symbols, and graph stats/integrity into one
InsightsModel dict. AC1: seeded decision/error/branches show up with real refs.
AC2: empty .cognirepo still yields real git-derived sections. AC3: no
FAISS/embedding calls. AC4: unit tests for both fixtures (this file).
"""
from __future__ import annotations

import subprocess


def _sh(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_git_repo(repo_dir):
    _sh("init", "-q", cwd=repo_dir)
    _sh("config", "user.email", "test@example.com", cwd=repo_dir)
    _sh("config", "user.name", "Test", cwd=repo_dir)
    (repo_dir / "README.md").write_text("hello\n", encoding="utf-8")
    _sh("add", ".", cwd=repo_dir)
    _sh("commit", "-q", "-m", "initial commit", cwd=repo_dir)
    _sh("branch", "feature/x", cwd=repo_dir)


def _log_decision(summary: str) -> str:
    from data.memory.episodic_memory import log_event  # pylint: disable=import-outside-toplevel
    log_event(f"decision: {summary}", metadata={"type": "decision", "summary": summary})
    from data.memory.episodic_memory import _load  # pylint: disable=import-outside-toplevel
    return _load()[-1]["id"]


def _record_error(error_type: str) -> None:
    from data.graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
    from data.graph.behaviour_tracker import BehaviourTracker  # pylint: disable=import-outside-toplevel
    bt = BehaviourTracker(KnowledgeGraph())
    bt.record_error(error_type, file_path="app.py", message="boom")
    bt.save()


class TestInsightsCollectorSeeded:
    def test_seeded_decision_error_branches_have_real_refs_ac1(self, tmp_path):
        _init_git_repo(tmp_path)
        episode_id = _log_decision("use FAISS for vector search")
        _record_error("ImportError")

        from intelligence.orchestrator import insights_collector

        model = insights_collector.collect(str(tmp_path), since="30d")

        assert model["decisions"]["status"] == "ok"
        assert model["decisions"]["items"][0]["ref"] == episode_id
        assert "FAISS" in model["decisions"]["items"][0]["summary"]

        assert model["errors"]["status"] == "ok"
        assert model["errors"]["items"][0]["ref"] == "ImportError"

        assert model["branches"]["status"] == "ok"
        names = {b["name"] for b in model["branches"]["items"]}
        assert names == {"master", "feature/x"} or names == {"main", "feature/x"}

        default = next(b for b in model["branches"]["items"] if b["is_default"])
        assert default["ahead"] == 0 and default["behind"] == 0
        feature = next(b for b in model["branches"]["items"] if b["name"] == "feature/x")
        assert feature["last_commit"]["hash"]

        assert model["meta"]["repo_root"] == str(tmp_path)
        assert model["meta"]["since"] == "30d"

    def test_no_faiss_or_embedding_calls_ac3(self, tmp_path, monkeypatch):
        _init_git_repo(tmp_path)

        def _boom(*_a, **_kw):
            raise AssertionError("insights_collector must not touch FAISS/embeddings")

        import faiss  # pylint: disable=import-outside-toplevel
        monkeypatch.setattr(faiss, "read_index", _boom)
        monkeypatch.setattr(faiss, "IndexFlatL2", _boom)

        from intelligence.orchestrator import insights_collector
        insights_collector.collect(str(tmp_path), since="30d")


class TestInsightsCollectorEmpty:
    def test_empty_cognirepo_yields_no_data_sections_ac2(self, tmp_path):
        _init_git_repo(tmp_path)

        from intelligence.orchestrator import insights_collector

        model = insights_collector.collect(str(tmp_path), since="30d")

        assert model["decisions"]["status"] == "no_data"
        assert model["errors"]["status"] == "no_data"
        assert model["hot_symbols"]["status"] == "no_data"
        assert model["index_health"]["status"] == "no_data"
        assert model["timeline"]["status"] == "no_data"

        # git-derived sections stay real even with an empty .cognirepo
        assert model["branches"]["status"] == "ok"
        assert len(model["branches"]["items"]) == 2
        assert model["commits_by_week"]["status"] == "ok"
        assert model["commits_by_week"]["weeks"][0]["commits"] == 1

    def test_no_branches_or_commits_when_not_a_git_repo(self, tmp_path):
        from intelligence.orchestrator import insights_collector

        model = insights_collector.collect(str(tmp_path), since="30d")

        assert model["branches"]["status"] == "no_data"
        assert model["commits_by_week"]["status"] == "no_data"
