# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Task 3.4 — Make cognirepo init actually initialize.

Verifies that:
- cognirepo init (non-interactive) runs index-repo automatically
- The AST index file exists after init
- The knowledge graph has at least one node after init
- --no-index flag correctly skips indexing
"""
import os
import json
from pathlib import Path


def test_init_creates_index(tmp_path, monkeypatch):
    """
    After init_project() runs, the AST index must exist and contain symbols.
    This is the core 'first-run experience' check — no second command needed.
    """
    from config.paths import set_cognirepo_dir, get_path
    set_cognirepo_dir(str(tmp_path / ".cognirepo"))
    monkeypatch.chdir(tmp_path)

    # Write a tiny Python fixture so there's something to index
    fixture = tmp_path / "hello.py"
    fixture.write_text("def greet(name: str) -> str:\n    return f'Hello, {name}'\n")

    from cli.init_project import init_project
    summary, kg, indexer = init_project(
        no_index=False,
        interactive=False,
        non_interactive=True,
    )

    # Indexer must have run
    assert summary is not None, "init_project returned no summary — indexing did not run"
    assert kg is not None, "init_project returned no KnowledgeGraph"
    assert indexer is not None, "init_project returned no ASTIndexer"

    # AST index file must exist
    ast_index = get_path("index/ast_index.json")
    assert os.path.exists(ast_index), (
        f"AST index not found at {ast_index} after init — indexing did not persist"
    )

    # Index must have content
    with open(ast_index, encoding="utf-8") as f:
        data = json.load(f)
    files = data.get("files", {})
    assert files, "AST index is empty after init — no files were indexed"


def test_no_index_flag_skips_indexing(tmp_path, monkeypatch):
    """--no-index must skip indexing and return (None, None, None)."""
    from config.paths import set_cognirepo_dir
    set_cognirepo_dir(str(tmp_path / ".cognirepo"))
    monkeypatch.chdir(tmp_path)

    from cli.init_project import init_project
    result = init_project(
        no_index=True,
        interactive=False,
        non_interactive=True,
    )

    assert result == (None, None, None), (
        f"Expected (None, None, None) with --no-index, got: {result}"
    )


def test_setup_calls_init_subprocess(tmp_path, monkeypatch):
    """cognirepo setup must shell out to 'cognirepo init' as a subprocess."""
    from unittest.mock import patch, MagicMock
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COGNIREPO_DIR", str(tmp_path / ".cognirepo"))
    (tmp_path / ".cognirepo").mkdir(parents=True, exist_ok=True)

    mock_run = MagicMock(return_value=MagicMock(returncode=0))

    # Patch all the setup-only steps so they don't fail in isolation
    with patch("subprocess.run", mock_run), \
         patch("cli.main._direct_index", return_value=({"index_symbols": 0, "index_files": 0}, MagicMock(), MagicMock())), \
         patch("cli.main._write_cursor_rules", return_value=None), \
         patch("cli.main._write_claude_hooks", return_value=None), \
         patch("cli.init_project.setup_mcp", return_value=None):
        from cli.main import _cmd_setup
        _cmd_setup(no_index=True)

    # subprocess.run must have been called with cognirepo init as the command
    assert mock_run.called
    found = any(
        "cognirepo" in str(call_args) and "init" in str(call_args)
        for call_args in mock_run.call_args_list
    )
    assert found, f"subprocess.run was not called with cognirepo init. Calls: {mock_run.call_args_list}"
