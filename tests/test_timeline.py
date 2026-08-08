# pylint: disable=missing-docstring, redefined-outer-name, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_timeline.py — COGNIREPO-204 acceptance criteria.

data/memory/timeline.py merges episodic (live + archive), session-exchange files,
and behaviour error patterns into one chronologically ordered view, plus a
deterministic template rollup.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.config.paths import get_path


def _write_session(sessions_dir: Path, session_id: str, created_at: str, user_msg: str) -> None:
    (sessions_dir / f"{session_id}.json").write_text(
        json.dumps({
            "session_id": session_id,
            "created_at": created_at,
            "model": "claude-sonnet-5",
            "messages": [
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": "ack"},
            ],
        }),
        encoding="utf-8",
    )


def _log_episode(event: str, ts_override: str, metadata: dict | None = None) -> None:
    """Log via the real episodic_memory module, then force a specific timestamp
    (log_event always stamps "now" — tests need controlled, distinct timestamps
    to assert ordering deterministically)."""
    from data.memory.episodic_memory import log_event, _load, _save  # pylint: disable=import-outside-toplevel
    log_event(event, metadata)
    data = _load()
    data[-1]["time"] = ts_override
    _save(data)


def _record_error(error_type: str, ts_override: str) -> None:
    from data.graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
    from data.graph.behaviour_tracker import BehaviourTracker  # pylint: disable=import-outside-toplevel
    bt = BehaviourTracker(KnowledgeGraph())
    bt.record_error(error_type, file_path="app.py", message="boom")
    bt.data["error_patterns"][error_type]["last_seen"] = ts_override
    bt.save()


class TestTimelineMerge:
    def test_merge_returns_seven_ordered_entries_ac1(self, tmp_path, monkeypatch):
        """AC1: 2 sessions + 3 episodes + 1 decision + 1 error -> 7 ordered entries;
        rollup names the decision and the error."""
        from data.memory import timeline

        sessions_dir = Path(get_path("sessions"))
        _write_session(sessions_dir, "s1", "2026-08-01T10:00:00+00:00", "how does auth work")
        _write_session(sessions_dir, "s2", "2026-08-02T10:00:00+00:00", "fix the flaky test")

        _log_episode("indexed repo", "2026-08-01T11:00:00+00:00")
        _log_episode("ran benchmark", "2026-08-02T11:00:00+00:00")
        _log_episode("reviewed PR", "2026-08-03T11:00:00+00:00")
        _log_episode(
            "decision: use FAISS for vector search", "2026-08-03T12:00:00+00:00",
            metadata={"type": "decision", "summary": "use FAISS for vector search"},
        )
        _record_error("ImportError", "2026-08-03T13:00:00+00:00")

        entries = timeline.merge(since="30d", limit=100)
        assert len(entries) == 7
        kinds = [e["kind"] for e in entries]
        assert kinds.count("session") == 2
        assert kinds.count("episode") == 3
        assert kinds.count("decision") == 1
        assert kinds.count("error") == 1

        # newest first
        timestamps = [e["ts"] for e in entries]
        assert timestamps == sorted(timestamps, reverse=True)

        rollup = timeline.rollup(entries)
        assert rollup["total"] == 7
        assert rollup["counts"] == {"session": 2, "episode": 3, "decision": 1, "error": 1}
        assert any("FAISS" in d for d in rollup["top_decisions"])
        assert any("ImportError" in e for e in rollup["top_errors"])

    def test_include_archived_default_excludes_ac2(self, tmp_path, monkeypatch):
        from data.memory import timeline
        from data.memory.episodic_memory import log_event

        log_event("live entry")
        archive_path = get_path("memory/episodic_archive.json")
        Path(archive_path).write_text(json.dumps([{
            "id": "e_archived_1", "event": "archived entry",
            "metadata": {}, "time": "2026-01-01T00:00:00+00:00",
        }]), encoding="utf-8")

        default_entries = timeline.merge(since="3650d", include_archived=False)
        assert "archived entry" not in [e["summary"] for e in default_entries]

        archived_entries = timeline.merge(since="3650d", include_archived=True)
        assert "archived entry" in [e["summary"] for e in archived_entries]

    def test_since_filters_old_entries(self, tmp_path, monkeypatch):
        from data.memory import timeline
        from datetime import datetime, timezone

        monkeypatch.setattr(timeline, "_now", lambda: datetime(2026, 8, 10, tzinfo=timezone.utc))
        _log_episode("very old event", "2020-01-01T00:00:00+00:00")
        _log_episode("recent event", "2026-08-05T00:00:00+00:00")

        entries = timeline.merge(since="30d")
        summaries = [e["summary"] for e in entries]
        assert "recent event" in summaries
        assert "very old event" not in summaries

    def test_deterministic_byte_identical_output_ac3(self, tmp_path, monkeypatch):
        from data.memory import timeline

        _write_session(Path(get_path("sessions")), "s1", "2026-08-01T10:00:00+00:00", "hello")
        _log_episode("event a", "2026-08-01T11:00:00+00:00")
        _log_episode("event b", "2026-08-01T11:00:00+00:00")  # same ts as "event a" — tie
        _record_error("TypeError", "2026-08-01T12:00:00+00:00")

        first = json.dumps(timeline.merge(since="30d"), sort_keys=True)
        second = json.dumps(timeline.merge(since="30d"), sort_keys=True)
        assert first == second

    def test_empty_store_returns_empty_list(self, tmp_path, monkeypatch):
        from data.memory import timeline
        assert timeline.merge() == []


class TestSessionParserExtraction:
    """Risk note: session-parser extraction must not change get_session_history
    behavior (golden test)."""

    def test_get_session_history_matches_parse_session_file(self, tmp_path, monkeypatch):
        from data.memory.timeline import parse_session_file
        from interface.server.mcp_server import get_session_history

        sessions_dir = Path(get_path("sessions"))
        _write_session(sessions_dir, "golden", "2026-08-01T10:00:00+00:00", "test query")

        via_tool = get_session_history(limit=5)
        assert len(via_tool) == 1

        via_parser = parse_session_file(str(sessions_dir / "golden.json"))
        assert via_tool[0] == via_parser

    def test_get_session_history_unaffected_by_current_json(self, tmp_path, monkeypatch):
        from interface.server.mcp_server import get_session_history

        sessions_dir = Path(get_path("sessions"))
        _write_session(sessions_dir, "real", "2026-08-01T10:00:00+00:00", "hi")
        (sessions_dir / "current.json").write_text('{"pointer": "real"}', encoding="utf-8")

        results = get_session_history(limit=10)
        assert len(results) == 1
        assert results[0]["session_id"] == "real"


class TestBootstrapTimelineDigest:
    def test_bootstrap_includes_recent_timeline(self, tmp_path, monkeypatch):
        from interface.server.mcp_server import get_agent_bootstrap

        _write_session(Path(get_path("sessions")), "s1", "2026-08-01T10:00:00+00:00", "hi")
        result = get_agent_bootstrap()
        assert "recent_timeline" in result
        assert isinstance(result["recent_timeline"], list)
