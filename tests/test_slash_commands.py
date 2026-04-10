# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""Tests for /save, /load, /index-repo slash commands."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cli.repl.ui import StdlibUI
from cli.repl.commands import dispatch


# ── capture helper ────────────────────────────────────────────────────────────

class _CaptureUI(StdlibUI):
    def __init__(self):
        self._output: list[str] = []

    def print(self, text: str, end: str = "\n") -> None:
        self._output.append(text)

    def status(self, text: str) -> None:
        self._output.append(text)

    def tier_label(self, tier: str, model: str) -> None:
        self._output.append(f"[{tier}→{model}]")

    def stream_chunks(self, chunks) -> str:
        return ""

    def spinner(self, message: str):
        from cli.repl.ui import _NullSpinner
        return _NullSpinner()


# ── /save ─────────────────────────────────────────────────────────────────────

def test_save_creates_session(tmp_path):
    ui = _CaptureUI()
    state = {
        "messages_history": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ],
        "force_model": None,
    }

    mock_session = {"session_id": "abc123def456", "messages": []}

    def fake_create(*a, **kw):
        return dict(mock_session)

    def fake_append(session, u, a, **kw):
        session["messages"].extend([
            {"role": "user", "content": u},
            {"role": "assistant", "content": a},
        ])
        return session

    with (
        patch("orchestrator.session.create_session", side_effect=fake_create),
        patch("orchestrator.session.append_exchange", side_effect=fake_append),
        patch("orchestrator.session._save_session"),
        patch("orchestrator.session._set_current"),
    ):
        result = dispatch("save", "my-session", ui, state)

    assert result is True
    assert state.get("session_id") == "abc123def456"
    assert any("abc123" in s for s in ui._output)


def test_save_empty_history(tmp_path):
    ui = _CaptureUI()
    state = {"messages_history": [], "force_model": None}

    mock_session = {"session_id": "aaa111", "messages": []}

    with (
        patch("orchestrator.session.create_session", return_value=dict(mock_session)),
        patch("orchestrator.session.append_exchange"),
        patch("orchestrator.session._save_session"),
        patch("orchestrator.session._set_current"),
    ):
        result = dispatch("save", "", ui, state)

    assert result is True


# ── /load ─────────────────────────────────────────────────────────────────────

def test_load_last_restores_messages():
    ui = _CaptureUI()
    state: dict = {"messages_history": []}

    fake_session = {
        "session_id": "sess999",
        "messages": [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
        ],
    }

    with patch("orchestrator.session.load_current_session", return_value=fake_session):
        result = dispatch("load", "last", ui, state)

    assert result is True
    assert state["messages_history"] == fake_session["messages"]
    assert state["session_id"] == "sess999"
    assert any("sess999" in s[:8] or "1 exchange" in s for s in ui._output)


def test_load_prefix_match():
    ui = _CaptureUI()
    state: dict = {"messages_history": []}

    fake_session = {
        "session_id": "abcd1234",
        "messages": [{"role": "user", "content": "hi"}],
    }

    with patch("orchestrator.session.find_session", return_value=fake_session):
        result = dispatch("load", "abcd", ui, state)

    assert result is True
    assert state["session_id"] == "abcd1234"


def test_load_not_found():
    ui = _CaptureUI()
    state: dict = {"messages_history": []}

    with patch("orchestrator.session.find_session", return_value=None):
        result = dispatch("load", "zzz999", ui, state)

    assert result is True
    assert any("No session found" in s for s in ui._output)


def test_load_no_args_prints_usage():
    ui = _CaptureUI()
    state: dict = {}
    result = dispatch("load", "", ui, state)
    assert result is True
    assert any("Usage" in s for s in ui._output)


# ── /index-repo ───────────────────────────────────────────────────────────────

def test_index_repo_success():
    ui = _CaptureUI()
    state: dict = {}

    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch("subprocess.run", return_value=mock_result):
        result = dispatch("index-repo", "", ui, state)

    assert result is True
    assert any("indexed" in s.lower() for s in ui._output)


def test_index_repo_failure():
    ui = _CaptureUI()
    state: dict = {}

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "Error: no files found"

    with patch("subprocess.run", return_value=mock_result):
        result = dispatch("index-repo", "", ui, state)

    assert result is True
    assert any("failed" in s.lower() for s in ui._output)


def test_index_repo_timeout():
    import subprocess
    ui = _CaptureUI()
    state: dict = {}

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 120)):
        result = dispatch("index-repo", "", ui, state)

    assert result is True
    assert any("timed out" in s.lower() for s in ui._output)
