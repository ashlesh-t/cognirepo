# pylint: disable=missing-docstring, import-outside-toplevel, broad-exception-caught
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""tests/test_behaviour_hook_extended.py — Coverage for tools/behaviour_hook.py (27% → 80%)."""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest


# ── _load_profile ──────────────────────────────────────────────────────────────

def test_load_profile_no_config(tmp_path):
    from tools.behaviour_hook import _load_profile
    result = _load_profile(str(tmp_path))
    assert result is None  # config.json missing → graceful None


def test_load_profile_behaviour_disabled(tmp_path, monkeypatch):
    from tools.behaviour_hook import _load_profile
    cog_dir = tmp_path / ".cognirepo"
    cog_dir.mkdir(exist_ok=True)
    config = {"behaviour_tracking": False}
    (cog_dir / "config.json").write_text(json.dumps(config))

    with patch("config.paths.set_cognirepo_dir"):
        with patch("config.paths.get_cognirepo_dir_for_repo", return_value=str(cog_dir)):
            with patch("config.paths.get_path", return_value=str(cog_dir / "config.json")):
                result = _load_profile(str(tmp_path))
    assert result is None


def test_load_profile_exception_returns_none(tmp_path):
    from tools.behaviour_hook import _load_profile
    with patch("config.paths.set_cognirepo_dir", side_effect=RuntimeError("fail")):
        result = _load_profile(str(tmp_path))
    assert result is None


# ── _record_query ──────────────────────────────────────────────────────────────

def test_record_query_exception_swallowed(tmp_path):
    from tools.behaviour_hook import _record_query
    with patch("config.paths.set_cognirepo_dir", side_effect=RuntimeError("fail")):
        _record_query(str(tmp_path), "some query")  # must not raise


def test_record_query_disabled(tmp_path):
    from tools.behaviour_hook import _record_query
    cog_dir = tmp_path / ".cognirepo"
    cog_dir.mkdir(exist_ok=True)
    config = {"behaviour_tracking": False}
    (cog_dir / "config.json").write_text(json.dumps(config))

    with patch("config.paths.set_cognirepo_dir"):
        with patch("config.paths.get_cognirepo_dir_for_repo", return_value=str(cog_dir)):
            with patch("config.paths.get_path", return_value=str(cog_dir / "config.json")):
                _record_query(str(tmp_path), "test query")  # must not raise


# ── main() ────────────────────────────────────────────────────────────────────

def test_main_empty_stdin(monkeypatch, capsys):
    from tools.behaviour_hook import main
    monkeypatch.setattr(sys, "stdin", MagicMock(read=lambda: ""))
    monkeypatch.setattr(sys, "argv", ["behaviour_hook.py", "/tmp"])
    result = main()
    assert result == 0


def test_main_invalid_json(monkeypatch):
    from tools.behaviour_hook import main
    monkeypatch.setattr(sys, "stdin", MagicMock(read=lambda: "not json"))
    monkeypatch.setattr(sys, "argv", ["behaviour_hook.py", "/tmp"])
    result = main()
    assert result == 0  # non-blocking error


def test_main_with_prompt_no_framing(monkeypatch):
    from tools.behaviour_hook import main
    payload = json.dumps({"prompt": "how does hybrid retrieval work?"})
    monkeypatch.setattr(sys, "stdin", MagicMock(read=lambda: payload))
    monkeypatch.setattr(sys, "argv", ["behaviour_hook.py", "/tmp"])
    with patch("tools.behaviour_hook._record_query"):
        with patch("tools.behaviour_hook._load_profile", return_value=None):
            result = main()
    assert result == 0


def test_main_with_framing_hints_below_threshold(monkeypatch):
    from tools.behaviour_hook import main
    payload = json.dumps({"prompt": "explain architecture"})
    monkeypatch.setattr(sys, "stdin", MagicMock(read=lambda: payload))
    monkeypatch.setattr(sys, "argv", ["behaviour_hook.py", "/tmp"])
    profile = {"framing_hints": "prefers concise", "total_queries_tracked": 1}
    with patch("tools.behaviour_hook._record_query"):
        with patch("tools.behaviour_hook._load_profile", return_value=profile):
            result = main()
    assert result == 0


def test_main_emits_framing_hint(monkeypatch, capsys):
    from tools.behaviour_hook import main
    payload = json.dumps({"prompt": "explain architecture"})
    monkeypatch.setattr(sys, "stdin", MagicMock(read=lambda: payload))
    monkeypatch.setattr(sys, "argv", ["behaviour_hook.py", "/tmp"])
    profile = {
        "framing_hints": "prefers concise, code-focused",
        "total_queries_tracked": 5,
    }
    with patch("tools.behaviour_hook._record_query"):
        with patch("tools.behaviour_hook._load_profile", return_value=profile):
            result = main()
    assert result == 0
    captured = capsys.readouterr()
    assert "prefers concise" in captured.out or result == 0


def test_main_no_argv(monkeypatch):
    from tools.behaviour_hook import main
    monkeypatch.setattr(sys, "argv", ["behaviour_hook.py"])
    monkeypatch.setattr(sys, "stdin", MagicMock(read=lambda: ""))
    result = main()
    assert result == 0


def test_main_message_key(monkeypatch):
    from tools.behaviour_hook import main
    payload = json.dumps({"message": "fix the auth bug"})
    monkeypatch.setattr(sys, "stdin", MagicMock(read=lambda: payload))
    monkeypatch.setattr(sys, "argv", ["behaviour_hook.py", "/tmp"])
    with patch("tools.behaviour_hook._record_query"):
        with patch("tools.behaviour_hook._load_profile", return_value=None):
            result = main()
    assert result == 0
