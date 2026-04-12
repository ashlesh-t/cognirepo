# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Tests for Sprint 2.4 — Zero-friction init: Cursor and VS Code MCP configs.

All tests run in a tmp_path so no real project files are modified.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from cli.init_project import _setup_cursor_mcp, _setup_vscode_mcp, setup_mcp


# ── _setup_cursor_mcp ─────────────────────────────────────────────────────────

def test_cursor_mcp_creates_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("shutil.which", return_value="/usr/bin/cognirepo"):
        _setup_cursor_mcp("myproject", str(tmp_path))
    mcp_path = tmp_path / ".cursor" / "mcp.json"
    assert mcp_path.exists()
    cfg = json.loads(mcp_path.read_text())
    assert "mcpServers" in cfg
    entries = cfg["mcpServers"]
    assert any("cognirepo" in k for k in entries)


def test_cursor_mcp_contains_project_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("shutil.which", return_value="/usr/bin/cognirepo"):
        _setup_cursor_mcp("proj", str(tmp_path))
    cfg = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())
    entry = next(v for v in cfg["mcpServers"].values())
    assert str(tmp_path) in entry["args"]


def test_cursor_mcp_idempotent(tmp_path, monkeypatch):
    """Re-running should update in place, not duplicate or wipe entries."""
    monkeypatch.chdir(tmp_path)
    existing = {"mcpServers": {"other-tool": {"command": "other", "args": []}}}
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "mcp.json").write_text(json.dumps(existing))

    with patch("shutil.which", return_value="/usr/bin/cognirepo"):
        _setup_cursor_mcp("proj", str(tmp_path))

    cfg = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())
    # Original entry preserved
    assert "other-tool" in cfg["mcpServers"]
    # cognirepo entry added
    assert any("cognirepo" in k for k in cfg["mcpServers"])


def test_cursor_mcp_no_binary_falls_back_to_python(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("shutil.which", return_value=None):
        _setup_cursor_mcp("proj", str(tmp_path))
    cfg = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())
    entry = next(v for v in cfg["mcpServers"].values())
    # Should fall back to sys.executable
    assert entry["command"].endswith("python") or entry["command"].endswith("python3") or "python" in entry["command"]


# ── _setup_vscode_mcp ─────────────────────────────────────────────────────────

def test_vscode_mcp_creates_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("shutil.which", return_value="/usr/bin/cognirepo"):
        _setup_vscode_mcp("myproject", str(tmp_path))
    mcp_path = tmp_path / ".vscode" / "mcp.json"
    assert mcp_path.exists()
    cfg = json.loads(mcp_path.read_text())
    assert "servers" in cfg


def test_vscode_mcp_has_type_stdio(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("shutil.which", return_value="/usr/bin/cognirepo"):
        _setup_vscode_mcp("proj", str(tmp_path))
    cfg = json.loads((tmp_path / ".vscode" / "mcp.json").read_text())
    entry = next(v for v in cfg["servers"].values())
    assert entry["type"] == "stdio"


def test_vscode_mcp_idempotent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    existing = {"servers": {"lsp-server": {"type": "stdio", "command": "node", "args": []}}}
    (tmp_path / ".vscode").mkdir()
    (tmp_path / ".vscode" / "mcp.json").write_text(json.dumps(existing))

    with patch("shutil.which", return_value="/usr/bin/cognirepo"):
        _setup_vscode_mcp("proj", str(tmp_path))

    cfg = json.loads((tmp_path / ".vscode" / "mcp.json").read_text())
    assert "lsp-server" in cfg["servers"]
    assert any("cognirepo" in k for k in cfg["servers"])


# ── setup_mcp dispatcher ──────────────────────────────────────────────────────

def test_setup_mcp_cursor_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("shutil.which", return_value="/usr/bin/cognirepo"):
        setup_mcp(["cursor"], "proj", str(tmp_path))
    assert (tmp_path / ".cursor" / "mcp.json").exists()
    assert not (tmp_path / ".vscode" / "mcp.json").exists()


def test_setup_mcp_vscode_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("shutil.which", return_value="/usr/bin/cognirepo"):
        setup_mcp(["vscode"], "proj", str(tmp_path))
    assert (tmp_path / ".vscode" / "mcp.json").exists()
    assert not (tmp_path / ".cursor" / "mcp.json").exists()


def test_setup_mcp_all_tools(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with (
        patch("shutil.which", return_value="/usr/bin/cognirepo"),
        patch("cli.init_project._setup_claude_mcp"),
        patch("cli.init_project._setup_gemini_mcp"),
    ):
        setup_mcp(["claude", "gemini", "cursor", "vscode"], "proj", str(tmp_path))
    assert (tmp_path / ".cursor" / "mcp.json").exists()
    assert (tmp_path / ".vscode" / "mcp.json").exists()


def test_setup_mcp_empty_targets(tmp_path, monkeypatch):
    """Empty targets list should write nothing."""
    monkeypatch.chdir(tmp_path)
    setup_mcp([], "proj", str(tmp_path))
    assert not (tmp_path / ".cursor").exists()
    assert not (tmp_path / ".vscode").exists()
