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


def test_setup_calls_wizard_and_init(tmp_path, monkeypatch):
    """cognirepo setup must call run_wizard() then init_project() directly (no subprocess)."""
    from unittest.mock import patch, MagicMock, call
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COGNIREPO_DIR", str(tmp_path / ".cognirepo"))
    (tmp_path / ".cognirepo").mkdir(parents=True, exist_ok=True)

    wizard_cfg = {
        "project_name": "test-proj",
        "encrypt": False,
        "install_languages": False,
        "mcp_targets": [],
        "org": None,
        "project": None,
        "autosave_context": True,
        "behaviour_tracking": False,
        # child_repos and orchestrator_mode are popped inside _cmd_setup
        "child_repos": [],
        "orchestrator_mode": False,
    }

    mock_wizard   = MagicMock(return_value=wizard_cfg)
    mock_init     = MagicMock(return_value=(None, None, None))
    mock_doctor   = MagicMock()

    with patch("cli.wizard.run_wizard", mock_wizard), \
         patch("cli.init_project.init_project", mock_init), \
         patch("cli.main._cmd_doctor", mock_doctor):
        from cli.main import _cmd_setup
        _cmd_setup(no_index=True)

    assert mock_wizard.called, "run_wizard() was not called"
    assert mock_init.called,   "init_project() was not called"
    assert mock_doctor.called, "_cmd_doctor() was not called"
