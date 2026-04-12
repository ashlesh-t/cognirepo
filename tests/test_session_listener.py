# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""Tests for server/session_listener.py — session-end hook."""
import json
import uuid
from pathlib import Path

from server.session_listener import on_session_end, recover_unclosed_sessions


def _make_session(sessions_dir: Path, messages: list, closed: bool = False) -> str:
    sid = uuid.uuid4().hex
    data = {
        "session_id": sid,
        "messages": messages,
        "created_at": "2026-01-01T00:00:00+00:00",
        "model": "claude-haiku-4-5",
    }
    if closed:
        data["closed_at"] = "2026-01-01T01:00:00+00:00"
    (sessions_dir / f"{sid}.json").write_text(json.dumps(data))
    return sid


def test_on_session_end_marks_closed(tmp_path, monkeypatch):
    sessions_dir = tmp_path / ".cognirepo" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("config.paths.get_path", lambda key: str(tmp_path / ".cognirepo" / key))
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / "global"))
    import memory.learning_store as ls
    ls._STORE = ls.CompositeLearningStore(project_dir=str(tmp_path))

    messages = [
        {"role": "user", "content": "how do I fix the async issue?"},
        {"role": "assistant", "content": "Fixed: the async db call was incorrect. Use await session.execute() instead."},
    ]
    sid = _make_session(sessions_dir, messages)

    on_session_end(sid)

    data = json.loads((sessions_dir / f"{sid}.json").read_text())
    assert "closed_at" in data


def test_on_session_end_idempotent(tmp_path, monkeypatch):
    sessions_dir = tmp_path / ".cognirepo" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("config.paths.get_path", lambda key: str(tmp_path / ".cognirepo" / key))
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / "global"))
    import memory.learning_store as ls
    ls._STORE = ls.CompositeLearningStore(project_dir=str(tmp_path))

    sid = _make_session(sessions_dir, [], closed=True)
    # Should not raise, even when already closed
    on_session_end(sid)


def test_recover_unclosed_sessions(tmp_path, monkeypatch):
    sessions_dir = tmp_path / ".cognirepo" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("config.paths.get_path", lambda key: str(tmp_path / ".cognirepo" / key))
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path / "global"))
    import memory.learning_store as ls
    ls._STORE = ls.CompositeLearningStore(project_dir=str(tmp_path))

    # Create 2 unclosed + 1 already closed
    _make_session(sessions_dir, [{"role": "assistant", "content": "some response text here " * 5}])
    _make_session(sessions_dir, [{"role": "assistant", "content": "another response " * 5}])
    _make_session(sessions_dir, [], closed=True)

    count = recover_unclosed_sessions()
    assert count == 2
