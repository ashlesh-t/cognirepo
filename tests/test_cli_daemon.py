# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Task 3.3 — Friendly OS check on cognirepo daemon / watch command.

Verifies that:
- On non-Linux platforms, a clear human-readable message is printed to stderr
  and the process exits with code 2 (not an ImportError traceback)
- fcntl import does not happen at module-level in cli/daemon.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_daemon_module_does_not_import_fcntl_at_toplevel():
    """
    cli/daemon.py must not import fcntl at module level.
    fcntl is Linux-only; importing it at the top level raises ImportError on Windows/macOS.
    """
    daemon_src = (ROOT / "cli" / "daemon.py").read_text(encoding="utf-8")
    lines = daemon_src.splitlines()
    # Find top-level import fcntl — must not appear before the first 'def ' or 'class '
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped in ("import fcntl", "import fcntl as _fcntl"):
            # Check if this line is inside a function (indented)
            assert line.startswith(" ") or line.startswith("\t"), (
                f"cli/daemon.py line {i+1}: top-level 'import fcntl' found — "
                "move it inside the function that uses it to avoid ImportError on non-Linux"
            )


def test_daemon_start_friendly_error_on_unsupported_os(monkeypatch, tmp_path, capsys):
    """
    When sys.platform is not 'linux', the watch command must print a friendly
    message to stderr and exit with code 2, not raise ImportError.
    """
    monkeypatch.setattr(sys, "platform", "darwin")  # simulate macOS

    # We need to call main() with 'watch --status' args
    import importlib
    import cli.main as main_mod
    importlib.reload(main_mod)

    import argparse

    # Patch sys.argv then call main — it should sys.exit(2)
    monkeypatch.setattr(sys, "argv", ["cognirepo", "watch", "--status"])

    try:
        main_mod.main()
        assert False, "Expected SystemExit(2)"
    except SystemExit as exc:
        assert exc.code == 2, f"Expected exit code 2, got {exc.code}"

    captured = capsys.readouterr()
    assert "Linux only" in captured.err or "linux" in captured.err.lower(), (
        f"Expected friendly 'Linux only' message in stderr, got: {captured.err!r}"
    )
