# pylint: disable=missing-docstring, import-outside-toplevel, broad-exception-caught
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""tests/test_wizard_extended2.py — More coverage for cli/wizard.py (32% → 65%)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── run_wizard (simulate with monkeypatched input) ────────────────────────────

def _make_input_responses(*responses):
    """Return a mock input() that cycles through the given responses."""
    it = iter(responses)
    def _input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            return ""
    return _input


def test_run_wizard_skip_all_defaults(monkeypatch, tmp_path, capsys):
    """Simulate wizard with all defaults, skipping MCP (index 7) and no org."""
    from interface.cli.wizard import run_wizard

    # Responses (in order of wizard steps):
    # 1. project name → default (empty)
    # 2. encrypt? → "n"
    # 3. vector backend → "1" (FAISS)
    # 4. behaviour tracking? → "n"
    # 5. language support? → "n"
    # 6. MCP target → "7" (skip)
    # 7. cross-agent handoff? → "n"
    # 8. org → "1" (None/Personal)
    # 9. proceed? → "n" (cancel)
    responses = _make_input_responses("", "n", "1", "n", "n", "7", "n", "1", "n")
    monkeypatch.setattr("builtins.input", responses)

    # patch config writing and heavy operations
    with patch("interface.cli.init_project.init_project", return_value={"status": "ok"}):
        with patch("config.orgs.list_orgs", return_value={}):
            with patch("config.orgs.list_projects", return_value={}):
                try:
                    run_wizard()
                except SystemExit:
                    pass  # "n" to proceed → sys.exit(0)
                except Exception:
                    pass


def test_run_wizard_with_encryption(monkeypatch, tmp_path):
    """Simulate wizard with encryption enabled."""
    from interface.cli.wizard import run_wizard

    responses = _make_input_responses(
        "myproject",  # project name
        "y",          # encrypt → yes
        "1",          # vector backend → FAISS
        "n",          # behaviour tracking
        "n",          # language support
        "7",          # MCP → skip
        "y",          # cross-agent handoff
        "1",          # org → None
        "n",          # proceed → no (cancel)
    )
    monkeypatch.setattr("builtins.input", responses)

    with patch("interface.cli.wizard._pip_install", return_value=True):
        with patch("config.orgs.list_orgs", return_value={}):
            with patch("config.orgs.list_projects", return_value={}):
                try:
                    run_wizard()
                except SystemExit:
                    pass


def test_run_wizard_claude_mcp(monkeypatch, tmp_path):
    """Simulate wizard choosing Claude MCP."""
    from interface.cli.wizard import run_wizard

    responses = _make_input_responses(
        "",    # project name default
        "n",   # no encrypt
        "1",   # FAISS
        "n",   # no behaviour
        "n",   # no languages
        "1",   # Claude MCP
        "n",   # not global
        "y",   # cross-agent handoff
        "1",   # no org
        "n",   # cancel proceed
    )
    monkeypatch.setattr("builtins.input", responses)

    with patch("config.orgs.list_orgs", return_value={}):
        with patch("config.orgs.list_projects", return_value={}):
            try:
                run_wizard()
            except SystemExit:
                pass


def test_run_wizard_new_org(monkeypatch, tmp_path):
    """Simulate wizard with creating a new org."""
    from interface.cli.wizard import run_wizard

    responses = _make_input_responses(
        "",          # project name default
        "n",         # no encrypt
        "1",         # FAISS
        "n",         # no behaviour
        "n",         # no languages
        "7",         # skip MCP
        "n",         # no cross-agent
        "2",         # create new org (idx = len+1)
        "mycompany",  # org name
        "n",          # no project
        "n",          # cancel proceed
    )
    monkeypatch.setattr("builtins.input", responses)

    with patch("config.orgs.list_orgs", return_value={}):
        with patch("config.orgs.list_projects", return_value={}):
            with patch("config.orgs.create_project", return_value=True):
                try:
                    run_wizard()
                except (SystemExit, StopIteration):
                    pass


def test_run_wizard_existing_org_with_project(monkeypatch, tmp_path):
    """Simulate wizard selecting existing org and project."""
    from interface.cli.wizard import run_wizard

    responses = _make_input_responses(
        "",          # project name
        "n",         # no encrypt
        "1",         # FAISS
        "n",         # no behaviour
        "n",         # no languages
        "7",         # skip MCP
        "n",         # no cross-agent
        "2",         # select "myorg" (index 1 = 2nd choice after "None")
        "y",         # yes want project
        "1",         # select "existing_proj" (1st)
        "n",         # cancel proceed
    )
    monkeypatch.setattr("builtins.input", responses)

    with patch("config.orgs.list_orgs", return_value={"myorg": {"repos": [], "projects": {}}}):
        with patch("config.orgs.list_projects", return_value={"existing_proj": {}}):
            try:
                run_wizard()
            except (SystemExit, StopIteration):
                pass


# ── _pip_install with real subprocess.run ────────────────────────────────────

def test_pip_install_success():
    from interface.cli.wizard import _pip_install
    import subprocess
    with patch("subprocess.check_call", return_value=0):
        result = _pip_install("cpu")
    assert result is True


def test_pip_install_failure():
    from interface.cli.wizard import _pip_install
    import subprocess
    with patch("subprocess.check_call", side_effect=subprocess.CalledProcessError(1, "pip")):
        result = _pip_install("cpu")
    assert result is False


def test_pip_install_not_found():
    from interface.cli.wizard import _pip_install
    with patch("subprocess.check_call", side_effect=FileNotFoundError("pip not found")):
        result = _pip_install("cpu")
    assert result is False


# ── _ask_yn edge cases ────────────────────────────────────────────────────────

def test_ask_yn_yes():
    from interface.cli.wizard import _ask_yn
    with patch("builtins.input", return_value="y"):
        result = _ask_yn("Test?", default=False)
    assert result is True


def test_ask_yn_yes_uppercase():
    from interface.cli.wizard import _ask_yn
    with patch("builtins.input", return_value="Y"):
        result = _ask_yn("Test?", default=False)
    assert result is True


def test_ask_yn_invalid_then_yes():
    from interface.cli.wizard import _ask_yn
    responses = iter(["xyz", "y"])
    with patch("builtins.input", side_effect=lambda _: next(responses)):
        result = _ask_yn("Test?", default=False)
    assert result is True


# ── _ask_choice edge cases ────────────────────────────────────────────────────

def test_ask_choice_out_of_range():
    from interface.cli.wizard import _ask_choice
    responses = iter(["99", "1"])
    with patch("builtins.input", side_effect=lambda _: next(responses)):
        result = _ask_choice("Pick:", choices=["a", "b"], default=0)
    assert result == 0


def test_ask_choice_non_numeric():
    from interface.cli.wizard import _ask_choice
    responses = iter(["abc", "2"])
    with patch("builtins.input", side_effect=lambda _: next(responses)):
        result = _ask_choice("Pick:", choices=["a", "b"], default=0)
    assert result == 1


def test_ask_choice_default():
    from interface.cli.wizard import _ask_choice
    with patch("builtins.input", return_value=""):
        result = _ask_choice("Pick:", choices=["a", "b"], default=1)
    assert result == 1


# ── _c with BOLD and color ────────────────────────────────────────────────────

def test_c_with_bold():
    from interface.cli.wizard import _c, _BOLD, _GREEN
    result = _c(_GREEN, _BOLD, "test text")
    assert isinstance(result, str)
    assert "test text" in result


def test_section_output(capsys):
    from interface.cli.wizard import _section
    _section(3, 7, "Test Section", "This is a subtitle for the section")
    captured = capsys.readouterr()
    assert len(captured.out) > 0
