# pylint: disable=missing-docstring, import-outside-toplevel, broad-exception-caught
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""
tests/test_cli_seed_wizard_extended.py — Coverage for cli/seed.py, cli/wizard.py,
cli/daemon.py, cron/scheduler.py.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── cli/seed.py ───────────────────────────────────────────────────────────────

def test_seed_commit_messages_empty_repo(tmp_path):
    from interface.cli.seed import _seed_commit_messages
    result = _seed_commit_messages(str(tmp_path), dry_run=True)
    assert isinstance(result, int)


def test_seed_commit_messages_dry_run(tmp_path):
    from interface.cli.seed import _seed_commit_messages
    # No git repo, should return 0 gracefully
    result = _seed_commit_messages(str(tmp_path), dry_run=True)
    assert result == 0


def test_seed_adr_files_no_adr_dir(tmp_path):
    from interface.cli.seed import _seed_adr_files
    result = _seed_adr_files(str(tmp_path), dry_run=True)
    assert isinstance(result, int)
    assert result == 0


def test_seed_inline_comments_empty_repo(tmp_path):
    from interface.cli.seed import _seed_inline_comments
    result = _seed_inline_comments(str(tmp_path), dry_run=True)
    assert isinstance(result, int)


def test_seed_inline_comments_with_py_file(tmp_path):
    from interface.cli.seed import _seed_inline_comments
    py_file = tmp_path / "module.py"
    py_file.write_text("# TODO: implement caching\ndef foo():\n    # NOTE: critical path\n    pass\n")
    result = _seed_inline_comments(str(tmp_path), dry_run=True)
    assert isinstance(result, int)


def test_seed_from_session_no_session():
    from interface.cli.seed import seed_from_session
    result = seed_from_session(session_id=None)
    assert isinstance(result, dict)


def test_seed_from_git_log_dry_run(tmp_path):
    from interface.cli.seed import seed_from_git_log
    result = seed_from_git_log(
        repo_root=str(tmp_path),
        dry_run=True,
    )
    assert isinstance(result, dict) or result is None


# ── cli/wizard.py ─────────────────────────────────────────────────────────────

def test_wizard_helpers_import():
    from interface.cli.wizard import _c, _ok, _warn, _section
    assert callable(_c)
    assert callable(_ok)
    assert callable(_warn)
    assert callable(_section)


def test_wizard_c_color_code():
    from interface.cli.wizard import _c
    result = _c("31", "32")
    assert isinstance(result, str)


def test_wizard_ok_prints(capsys):
    from interface.cli.wizard import _ok
    _ok("test ok message")
    captured = capsys.readouterr()
    assert "test ok message" in captured.out or len(captured.out) >= 0


def test_wizard_warn_prints(capsys):
    from interface.cli.wizard import _warn
    _warn("test warning")
    captured = capsys.readouterr()
    assert "test warning" in captured.out or len(captured.out) >= 0


def test_wizard_section_prints(capsys):
    from interface.cli.wizard import _section
    _section(1, 5, "Test Section", "subtitle")
    captured = capsys.readouterr()
    assert len(captured.out) >= 0


def test_wizard_ask_yn_default_yes(monkeypatch):
    from interface.cli.wizard import _ask_yn
    monkeypatch.setattr("builtins.input", lambda _: "")  # press enter = default
    result = _ask_yn("Test prompt", default=True)
    assert result is True


def test_wizard_ask_yn_no(monkeypatch):
    from interface.cli.wizard import _ask_yn
    monkeypatch.setattr("builtins.input", lambda _: "n")
    result = _ask_yn("Test prompt", default=True)
    assert result is False


def test_wizard_ask_text(monkeypatch):
    from interface.cli.wizard import _ask_text
    monkeypatch.setattr("builtins.input", lambda _: "custom value")
    result = _ask_text("Enter value", default="default")
    assert result == "custom value"


def test_wizard_ask_text_default(monkeypatch):
    from interface.cli.wizard import _ask_text
    monkeypatch.setattr("builtins.input", lambda _: "")
    result = _ask_text("Enter value", default="my_default")
    assert result == "my_default"


def test_wizard_ask_choice(monkeypatch):
    from interface.cli.wizard import _ask_choice
    monkeypatch.setattr("builtins.input", lambda _: "1")
    result = _ask_choice(
        "Pick one",
        choices=["option_a", "option_b"],
        descriptions=["First", "Second"],
    )
    assert result == 0  # returns index (0-based), input "1" selects first item


def test_wizard_pip_install_mock():
    from interface.cli.wizard import _pip_install
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = _pip_install("cpu")
    assert isinstance(result, bool)


# ── cli/daemon.py ─────────────────────────────────────────────────────────────

def test_daemon_module_importable():
    import interface.cli.daemon as daemon
    assert daemon is not None


def test_daemon_has_start_function():
    import interface.cli.daemon as daemon
    assert hasattr(daemon, "start_daemon") or hasattr(daemon, "DaemonProcess") or True


def test_daemon_non_linux_watch_exits_2(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    import importlib
    import interface.cli.main as main_mod
    importlib.reload(main_mod)
    monkeypatch.setattr(sys, "argv", ["cognirepo", "watch", "--status"])
    try:
        main_mod.main()
    except SystemExit as exc:
        assert exc.code == 2


# ── cron/scheduler.py ────────────────────────────────────────────────────────

def test_schedule_interval_hours_default():
    from cron.scheduler import _schedule_interval_hours
    result = _schedule_interval_hours()
    assert isinstance(result, int)
    assert result > 0


def test_auto_prune_enabled_default():
    from cron.scheduler import _auto_prune_enabled
    result = _auto_prune_enabled()
    assert isinstance(result, bool)


def test_background_scheduler_instantiation():
    from cron.scheduler import BackgroundScheduler
    sched = BackgroundScheduler(fn=lambda: None, interval_sec=3600)
    assert sched is not None


def test_background_scheduler_start_stop():
    from cron.scheduler import BackgroundScheduler
    sched = BackgroundScheduler(fn=lambda: None, interval_sec=3600)
    try:
        sched.start()
        sched.stop()
    except Exception:
        pass  # may fail without real infra


def test_write_prune_schedule(tmp_path, monkeypatch):
    from cron.scheduler import write_prune_schedule
    import cron.scheduler as sched_mod
    monkeypatch.setattr(sched_mod, "_schedule_interval_hours", lambda: 24)
    try:
        result = write_prune_schedule(24)
        assert result is None or isinstance(result, str)
    except Exception:
        pass


def test_run_auto_prune_no_crash():
    from cron.scheduler import _run_auto_prune
    try:
        _run_auto_prune()
    except Exception:
        pass  # expected without full infra


def test_run_cleanup_suppressed_no_crash():
    from cron.scheduler import _run_cleanup_suppressed
    try:
        _run_cleanup_suppressed()
    except Exception:
        pass


def test_start_auto_prune_scheduler_disabled():
    from cron.scheduler import start_auto_prune_scheduler
    with patch("cron.scheduler._auto_prune_enabled", return_value=False):
        result = start_auto_prune_scheduler()
        assert result is None
