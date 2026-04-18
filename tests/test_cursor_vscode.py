# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_cursor_vscode.py — Sprint 5 / TASK-014 acceptance tests.

Covers:
  - _setup_cursor_mcp() writes .cursor/mcp.json with mcpServers entry
  - _setup_vscode_mcp() writes .vscode/mcp.json with servers/type=stdio entry
  - setup_mcp() dispatches to both when targets include "cursor" and "vscode"
  - Config generation is idempotent (re-run merges, does not overwrite siblings)
  - cognirepo doctor can validate the files exist and are valid JSON
"""
from __future__ import annotations
import os

import json
from pathlib import Path


# ── helpers ───────────────────────────────────────────────────────────────────

def _run_in(tmp_path: Path, fn):
    """Change to tmp_path, run fn(), then restore cwd."""
    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        return fn()
    finally:
        os.chdir(orig)


# ── _setup_cursor_mcp ─────────────────────────────────────────────────────────

class TestCursorMCP:
    def test_creates_cursor_mcp_json(self, tmp_path):
        """.cursor/mcp.json must be created with mcpServers entry."""
        from cli.init_project import _setup_cursor_mcp

        _run_in(tmp_path, lambda: _setup_cursor_mcp("myproject", str(tmp_path)))

        mcp_file = tmp_path / ".cursor" / "mcp.json"
        assert mcp_file.exists(), ".cursor/mcp.json was not created"
        cfg = json.loads(mcp_file.read_text())
        assert "mcpServers" in cfg
        assert len(cfg["mcpServers"]) >= 1
        server_entry = next(iter(cfg["mcpServers"].values()))
        assert "command" in server_entry
        assert "args" in server_entry
        assert str(tmp_path) in server_entry["args"]

    def test_server_name_includes_project_name(self, tmp_path):
        from cli.init_project import _setup_cursor_mcp

        _run_in(tmp_path, lambda: _setup_cursor_mcp("cool_project", str(tmp_path)))

        cfg = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())
        server_names = list(cfg["mcpServers"].keys())
        assert any("cool_project" in name for name in server_names)

    def test_idempotent_does_not_delete_siblings(self, tmp_path):
        """Running twice keeps pre-existing mcpServers entries."""
        from cli.init_project import _setup_cursor_mcp

        # Pre-populate with a different server entry
        cursor_dir = tmp_path / ".cursor"
        cursor_dir.mkdir()
        existing = {"mcpServers": {"other-tool": {"command": "other", "args": []}}}
        (cursor_dir / "mcp.json").write_text(json.dumps(existing))

        _run_in(tmp_path, lambda: _setup_cursor_mcp("myproject", str(tmp_path)))

        cfg = json.loads((cursor_dir / "mcp.json").read_text())
        assert "other-tool" in cfg["mcpServers"], "Pre-existing entry was overwritten"
        assert any("myproject" in k for k in cfg["mcpServers"])

    def test_valid_json_output(self, tmp_path):
        from cli.init_project import _setup_cursor_mcp

        _run_in(tmp_path, lambda: _setup_cursor_mcp("proj", str(tmp_path)))

        raw = (tmp_path / ".cursor" / "mcp.json").read_text()
        parsed = json.loads(raw)  # raises if invalid JSON
        assert isinstance(parsed, dict)


# ── _setup_vscode_mcp ─────────────────────────────────────────────────────────

class TestVSCodeMCP:
    def test_creates_vscode_mcp_json(self, tmp_path):
        """.vscode/mcp.json must be created with servers entry."""
        from cli.init_project import _setup_vscode_mcp

        _run_in(tmp_path, lambda: _setup_vscode_mcp("myproject", str(tmp_path)))

        mcp_file = tmp_path / ".vscode" / "mcp.json"
        assert mcp_file.exists(), ".vscode/mcp.json was not created"
        cfg = json.loads(mcp_file.read_text())
        assert "servers" in cfg
        server_entry = next(iter(cfg["servers"].values()))
        assert server_entry.get("type") == "stdio"
        assert "command" in server_entry
        assert "args" in server_entry

    def test_type_is_stdio(self, tmp_path):
        """VS Code MCP entries must have type=stdio."""
        from cli.init_project import _setup_vscode_mcp

        _run_in(tmp_path, lambda: _setup_vscode_mcp("proj", str(tmp_path)))

        cfg = json.loads((tmp_path / ".vscode" / "mcp.json").read_text())
        for entry in cfg["servers"].values():
            assert entry["type"] == "stdio"

    def test_idempotent_does_not_delete_siblings(self, tmp_path):
        from cli.init_project import _setup_vscode_mcp

        vscode_dir = tmp_path / ".vscode"
        vscode_dir.mkdir()
        existing = {"servers": {"other-tool": {"type": "stdio", "command": "x", "args": []}}}
        (vscode_dir / "mcp.json").write_text(json.dumps(existing))

        _run_in(tmp_path, lambda: _setup_vscode_mcp("myproject", str(tmp_path)))

        cfg = json.loads((vscode_dir / "mcp.json").read_text())
        assert "other-tool" in cfg["servers"]
        assert any("myproject" in k for k in cfg["servers"])

    def test_valid_json_output(self, tmp_path):
        from cli.init_project import _setup_vscode_mcp

        _run_in(tmp_path, lambda: _setup_vscode_mcp("proj", str(tmp_path)))

        raw = (tmp_path / ".vscode" / "mcp.json").read_text()
        assert isinstance(json.loads(raw), dict)


# ── setup_mcp dispatch ────────────────────────────────────────────────────────

class TestSetupMCPDispatch:
    def test_cursor_target_creates_cursor_file(self, tmp_path):
        from cli.init_project import setup_mcp

        _run_in(tmp_path, lambda: setup_mcp(
            targets=["cursor"], project_name="p", project_path=str(tmp_path)
        ))

        assert (tmp_path / ".cursor" / "mcp.json").exists()
        assert not (tmp_path / ".vscode" / "mcp.json").exists()

    def test_vscode_target_creates_vscode_file(self, tmp_path):
        from cli.init_project import setup_mcp

        _run_in(tmp_path, lambda: setup_mcp(
            targets=["vscode"], project_name="p", project_path=str(tmp_path)
        ))

        assert (tmp_path / ".vscode" / "mcp.json").exists()
        assert not (tmp_path / ".cursor" / "mcp.json").exists()

    def test_both_targets_create_both_files(self, tmp_path):
        from cli.init_project import setup_mcp

        _run_in(tmp_path, lambda: setup_mcp(
            targets=["cursor", "vscode"], project_name="p", project_path=str(tmp_path)
        ))

        assert (tmp_path / ".cursor" / "mcp.json").exists()
        assert (tmp_path / ".vscode" / "mcp.json").exists()

    def test_empty_targets_creates_nothing(self, tmp_path):
        from cli.init_project import setup_mcp

        _run_in(tmp_path, lambda: setup_mcp(
            targets=[], project_name="p", project_path=str(tmp_path)
        ))

        assert not (tmp_path / ".cursor").exists()
        assert not (tmp_path / ".vscode").exists()


# ── doctor validation helper ──────────────────────────────────────────────────

class TestDoctorValidation:
    def test_cursor_config_is_valid_json(self, tmp_path):
        """Simulate what cognirepo doctor does: read and parse the config."""
        from cli.init_project import _setup_cursor_mcp

        _run_in(tmp_path, lambda: _setup_cursor_mcp("proj", str(tmp_path)))

        cursor_cfg = tmp_path / ".cursor" / "mcp.json"
        assert cursor_cfg.exists()
        try:
            cfg = json.loads(cursor_cfg.read_text())
            assert "mcpServers" in cfg
            valid = True
        except (json.JSONDecodeError, KeyError):
            valid = False
        assert valid

    def test_vscode_config_is_valid_json(self, tmp_path):
        from cli.init_project import _setup_vscode_mcp

        _run_in(tmp_path, lambda: _setup_vscode_mcp("proj", str(tmp_path)))

        vscode_cfg = tmp_path / ".vscode" / "mcp.json"
        assert vscode_cfg.exists()
        cfg = json.loads(vscode_cfg.read_text())
        assert "servers" in cfg
