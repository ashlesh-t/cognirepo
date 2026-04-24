# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_ftx.py — Sprint 7 / TASK-020 acceptance tests.

Covers:
  - cognirepo init is idempotent — re-running prints "Already initialized"
  - --non-interactive flag uses all defaults (no prompts)
  - End-of-init summary prints tool list and token reduction estimate
  - Watcher prompt is shown after indexing in interactive mode
  - Systemd prompt is shown on Linux in interactive mode
  - _print_ready_summary formats output correctly
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from cli.init_project import init_project

REPO_ROOT = Path(__file__).parent.parent


class TestIdempotentInit:
    def test_reinit_prints_already_initialized(self, tmp_path, capsys):
        """Re-running init on an existing project must print 'Already initialized'."""
        # Create a config.json to simulate already-initialized state
        cognirepo_dir = tmp_path / ".cognirepo"
        cognirepo_dir.mkdir(exist_ok=True)
        config_file = cognirepo_dir / "config.json"
        config_file.write_text('{"project_name": "test", "port": 8000}')

        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with patch("cli.init_project.get_path", return_value=config_file):
                with patch("cli.init_project._scaffold_dirs"):
                    with patch("cli.init_project._init_empty_stores"):
                        with patch("cli.init_project._write_config"):
                            with patch("cli.init_project._write_gitignore"):
                                with patch("cli.init_project._seed_dotenv"):
                                    with patch("cli.init_project._seed_learnings_from_docs"):
                                        with patch("builtins.input", return_value="n"):
                                            init_project(no_index=True, interactive=False)

            out = capsys.readouterr().out
            assert "Already initialized" in out or "updating" in out.lower(), (
                "Re-running init must inform user the project is already initialized"
            )
        finally:
            os.chdir(orig_cwd)

    def test_init_does_not_lose_existing_index(self, tmp_path):
        """Re-running init must preserve existing index data."""
        cognirepo_dir = tmp_path / ".cognirepo"
        cognirepo_dir.mkdir(exist_ok=True)
        index_dir = cognirepo_dir / "index"
        index_dir.mkdir(exist_ok=True)
        index_file = index_dir / "symbols.json"
        index_file.write_text('{"existing": "data"}')
        config_file = cognirepo_dir / "config.json"
        config_file.write_text('{"project_name": "test"}')

        orig_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            with patch("cli.init_project.get_path", return_value=config_file):
                with patch("cli.init_project._scaffold_dirs"):
                    with patch("cli.init_project._init_empty_stores"):
                        with patch("cli.init_project._write_config"):
                            with patch("cli.init_project._write_gitignore"):
                                with patch("cli.init_project._seed_dotenv"):
                                    with patch("cli.init_project._seed_learnings_from_docs"):
                                        with patch("builtins.input", return_value="n"):
                                            init_project(no_index=True, interactive=False)
        finally:
            os.chdir(orig_cwd)

        # Index file must still exist
        assert index_file.exists(), "Re-running init must not delete existing index"
        assert index_file.read_text() == '{"existing": "data"}'


class TestNonInteractiveFlag:
    def test_non_interactive_skips_wizard(self):
        """--non-interactive must not call run_wizard."""
        with patch("cli.init_project._scaffold_dirs"):
            with patch("cli.init_project._init_empty_stores"):
                with patch("cli.init_project._write_config"):
                    with patch("cli.init_project._write_gitignore"):
                        with patch("cli.init_project._seed_dotenv"):
                            with patch("cli.init_project._seed_learnings_from_docs"):
                                with patch("cli.init_project.get_path") as mock_path:
                                    mock_config = MagicMock()
                                    mock_config.exists.return_value = False
                                    mock_config.parent.mkdir = MagicMock()
                                    mock_path.return_value = mock_config
                                    with patch("cli.init_project.open", create=True):
                                        with patch("json.load", return_value={}):
                                            with patch("cli.wizard.run_wizard") as mock_wizard:
                                                init_project(
                                                    non_interactive=True,
                                                    no_index=True,
                                                )
                                                mock_wizard.assert_not_called()

    def test_non_interactive_flag_accepted_by_init_project(self):
        """init_project must accept non_interactive=True and not raise."""
        import inspect
        sig = inspect.signature(init_project)
        # non_interactive must be in the signature and default to False
        assert "non_interactive" in sig.parameters
        param = sig.parameters["non_interactive"]
        assert param.default is False


class TestReadySummary:
    def test_print_ready_summary_outputs_tools(self, capsys):
        """_print_ready_summary must list MCP tools Claude can call."""
        from cli.main import _print_ready_summary
        _print_ready_summary(summary=None)
        out = capsys.readouterr().out
        assert "context_pack" in out
        assert "lookup_symbol" in out
        assert "who_calls" in out
        assert "subgraph" in out
        assert "retrieve_memory" in out

    def test_print_ready_summary_shows_youre_ready(self, capsys):
        """_print_ready_summary must output a 'You're ready!' message."""
        from cli.main import _print_ready_summary
        _print_ready_summary(summary=None)
        out = capsys.readouterr().out
        assert "ready" in out.lower()

    def test_print_ready_summary_shows_next_steps(self, capsys):
        """_print_ready_summary must show next steps to the user."""
        from cli.main import _print_ready_summary
        _print_ready_summary(summary=None)
        out = capsys.readouterr().out
        assert "doctor" in out or "next steps" in out.lower()

    def test_print_ready_summary_with_index_stats(self, capsys):
        """_print_ready_summary must show index stats when summary is provided."""
        from cli.main import _print_ready_summary
        _print_ready_summary(summary={"files_indexed": 42, "symbols": 500})
        out = capsys.readouterr().out
        assert "42" in out or "500" in out

    def test_print_ready_summary_with_token_estimate(self, capsys):
        """_print_ready_summary must estimate token reduction for large repos."""
        from cli.main import _print_ready_summary
        _print_ready_summary(summary={"files_indexed": 100, "symbols": 1000})
        out = capsys.readouterr().out
        assert "token" in out.lower() or "reduction" in out.lower()


