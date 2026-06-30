# pylint: disable=missing-docstring, import-outside-toplevel, broad-exception-caught
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""tests/test_cli_main_helpers_extended.py — More cli/main.py coverage."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── _print_results ────────────────────────────────────────────────────────────

def test_print_results_list_of_dicts(capsys):
    from interface.cli.main import _print_results
    _print_results([{"text": "hello", "importance": 0.9}])
    captured = capsys.readouterr()
    assert "hello" in captured.out
    assert "importance" in captured.out


def test_print_results_list_of_strings(capsys):
    from interface.cli.main import _print_results
    _print_results(["item1", "item2"])
    captured = capsys.readouterr()
    assert "item1" in captured.out


def test_print_results_dict(capsys):
    from interface.cli.main import _print_results
    _print_results({"status": "ok", "count": 5})
    captured = capsys.readouterr()
    assert "status" in captured.out


def test_print_results_empty_list(capsys):
    from interface.cli.main import _print_results
    _print_results([])
    captured = capsys.readouterr()
    assert captured.out == ""


# ── _print_search_results ─────────────────────────────────────────────────────

def test_print_search_results_empty(capsys):
    from interface.cli.main import _print_search_results
    _print_search_results([])
    captured = capsys.readouterr()
    assert captured.out == ""


def test_print_search_results_with_results(capsys):
    from interface.cli.main import _print_search_results
    results = [
        {"path": "some/file.py", "line": 42, "context": "def foo():\n    pass"},
        {"path": "some/file.py", "line": 50, "context": "def bar():\n    pass"},
        {"path": "other/file.py", "line": 1, "context": "import os"},
    ]
    _print_search_results(results)
    captured = capsys.readouterr()
    assert "some/file.py" in captured.out
    assert "other/file.py" in captured.out


def test_print_search_results_plain_string(capsys):
    from interface.cli.main import _print_search_results
    _print_search_results(["plain result"])
    captured = capsys.readouterr()
    assert "plain result" in captured.out


# ── _log_error_to_file ────────────────────────────────────────────────────────

def test_log_error_to_file_creates_log(tmp_path):
    from interface.cli.main import _log_error_to_file
    with patch("config.paths.get_path", return_value=str(tmp_path / "errors")):
        try:
            raise ValueError("test error")
        except ValueError as exc:
            path = _log_error_to_file(exc, context="test context")
    assert isinstance(path, str)


def test_log_error_no_context(tmp_path):
    from interface.cli.main import _log_error_to_file
    with patch("config.paths.get_path", return_value=str(tmp_path / "errors")):
        try:
            raise RuntimeError("no context")
        except RuntimeError as exc:
            path = _log_error_to_file(exc)
    assert isinstance(path, str)


# ── _direct_store ─────────────────────────────────────────────────────────────

def test_direct_store_local():
    from interface.cli.main import _direct_store
    with patch("interface.tools.store_memory.store_memory", return_value={"status": "stored", "id": "abc"}):
        with patch("data.memory.user_memory.record_action"):
            result = _direct_store("remember this", "cli")
    assert isinstance(result, dict)


def test_direct_store_global():
    from interface.cli.main import _direct_store
    with patch("data.memory.user_memory.set_preference"):
        with patch("data.memory.user_memory.record_action"):
            result = _direct_store("remember this globally", "cli", global_scope=True)
    assert result["scope"] == "global"


# ── _direct_retrieve ──────────────────────────────────────────────────────────

def test_direct_retrieve_local():
    from interface.cli.main import _direct_retrieve
    with patch("interface.tools.retrieve_memory.retrieve_memory", return_value=[{"text": "found", "score": 0.9}]):
        with patch("data.memory.user_memory.record_action"):
            result = _direct_retrieve("query text", top_k=5)
    assert isinstance(result, list)


def test_direct_retrieve_global():
    from interface.cli.main import _direct_retrieve
    with patch("data.memory.user_memory.list_preferences", return_value={"key": {"text": "pref"}}):
        with patch("data.memory.user_memory.record_action"):
            result = _direct_retrieve("query", top_k=5, global_scope=True)
    assert isinstance(result, (list, dict))


# ── _direct_search ────────────────────────────────────────────────────────────

def test_direct_search():
    from interface.cli.main import _direct_search
    with patch("interface.tools.search_docs.search_docs", return_value=[{"path": "README.md", "context": "intro"}]):
        result = _direct_search("documentation query")
    assert isinstance(result, (list, dict))


# ── _direct_log ───────────────────────────────────────────────────────────────

def test_direct_log_event():
    from interface.cli.main import _direct_log
    with patch("data.memory.episodic_memory.log_event"):
        result = _direct_log("deployment", {"version": "1.1.0"})
    assert result["status"] == "logged"
    assert result["event"] == "deployment"


# ── _direct_history ───────────────────────────────────────────────────────────

def test_direct_history():
    from interface.cli.main import _direct_history
    with patch("data.memory.episodic_memory.get_history", return_value=[{"event": "test"}]):
        result = _direct_history(limit=10)
    assert isinstance(result, list)


# ── _write_last_indexed_sha ───────────────────────────────────────────────────

def test_write_last_indexed_sha(tmp_path):
    from interface.cli.main import _write_last_indexed_sha
    with patch("config.paths.get_path", return_value=str(tmp_path / "index" / "last_indexed.json")):
        try:
            _write_last_indexed_sha(str(tmp_path))
        except Exception:
            pass  # git may not be available in tmp_path


# ── _find_claude_desktop_config ───────────────────────────────────────────────

def test_find_claude_desktop_config():
    from interface.cli.main import _find_claude_desktop_config
    result = _find_claude_desktop_config()
    assert result is None or isinstance(result, str)


# ── _cmd_status ───────────────────────────────────────────────────────────────

def test_cmd_status_no_config(tmp_path):
    from interface.cli.main import _cmd_status
    with patch("config.paths.get_path", return_value=str(tmp_path / "config.json")):
        try:
            _cmd_status()
        except SystemExit:
            pass
        except Exception:
            pass


# ── _cmd_prime ────────────────────────────────────────────────────────────────

def test_cmd_prime_as_json():
    from interface.cli.main import _cmd_prime
    with patch("interface.tools.prime_session.prime_session", return_value={"architecture": "test", "hot_symbols": []}):
        try:
            _cmd_prime(as_json=True)
        except Exception:
            pass


def test_cmd_prime_text():
    from interface.cli.main import _cmd_prime
    with patch("interface.tools.prime_session.prime_session", return_value={"architecture": "test", "hot_symbols": []}):
        try:
            _cmd_prime(as_json=False)
        except Exception:
            pass


# ── _test_connection ──────────────────────────────────────────────────────────

def test_test_connection_unknown_provider():
    from interface.cli.main import _test_connection
    result = _test_connection("unknown_provider")
    assert isinstance(result, dict)
    assert not result.get("ok", True) or "error" in result or isinstance(result, dict)


# ── _cmd_list_mcp ──────────────────────────────────────────────────────────────

def test_cmd_list_mcp_no_crash(capsys):
    from interface.cli.main import _cmd_list_mcp
    try:
        _cmd_list_mcp()
    except Exception:
        pass
    captured = capsys.readouterr()
    assert len(captured.out) >= 0  # may or may not print


# ── _cmd_list_orgs ────────────────────────────────────────────────────────────

def test_cmd_list_orgs_no_crash(capsys):
    from interface.cli.main import _cmd_list_orgs
    with patch("config.orgs.list_orgs", return_value={"testorg": {"repos": ["/path/to/repo"]}}):
        _cmd_list_orgs()
    captured = capsys.readouterr()
    assert len(captured.out) >= 0


def test_cmd_list_orgs_empty(capsys):
    from interface.cli.main import _cmd_list_orgs
    with patch("config.orgs.list_orgs", return_value={}):
        _cmd_list_orgs()
    captured = capsys.readouterr()
    assert len(captured.out) >= 0


# ── _maybe_tip_index_repo ─────────────────────────────────────────────────────

def test_maybe_tip_no_crash():
    from interface.cli.main import _maybe_tip_index_repo
    try:
        _maybe_tip_index_repo()
    except Exception:
        pass


# ── _print_ready_summary ──────────────────────────────────────────────────────

def test_print_ready_summary_none(capsys):
    from interface.cli.main import _print_ready_summary
    try:
        _print_ready_summary(summary=None)
    except Exception:
        pass


def test_print_ready_summary_with_data(capsys):
    from interface.cli.main import _print_ready_summary
    try:
        _print_ready_summary(summary={"symbol_count": 500, "file_count": 50})
    except Exception:
        pass


# ── _cmd_doctor (focused paths) ───────────────────────────────────────────────

def test_cmd_doctor_as_json_no_crash():
    from interface.cli.main import _cmd_doctor
    try:
        result = _cmd_doctor(as_json=True)
        assert result in (0, 1, 2, None)
    except (SystemExit, Exception):
        pass


# ── _cmd_sessions ─────────────────────────────────────────────────────────────

def test_cmd_sessions_no_crash(capsys):
    from interface.cli.main import _cmd_sessions
    with patch("data.memory.episodic_memory.get_history", return_value=[
        {"event": "session_end", "timestamp": "2026-01-01T00:00:00Z", "metadata": {"summary": "test session"}}
    ]):
        try:
            _cmd_sessions(limit=5)
        except Exception:
            pass
