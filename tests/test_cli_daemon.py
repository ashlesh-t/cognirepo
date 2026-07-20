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
    daemon_src = (ROOT / "interface" / "cli" / "daemon.py").read_text(encoding="utf-8")
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
    import interface.cli.main as main_mod
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


class TestRunWatcherWithCrashGuardKeyboardInterrupt:
    """COGNIREPO-D05: the KeyboardInterrupt branch (Ctrl+C / SIGTERM — the
    primary real-world shutdown path, both raise KeyboardInterrupt via the
    installed SIGTERM handler) must call stop_fn(observer) before breaking
    out of the loop. Without this, _flush_and_stop_observer()'s flush()
    never runs on a real shutdown and any debounced-but-unflushed edit is
    silently dropped — confirmed by a live cognirepo watch + SIGTERM +
    index-content check before this fix, which reproduced the exact D05
    data-loss bug even with _stop_observer()/_stop() already patched."""

    def test_stop_fn_called_on_keyboard_interrupt(self, monkeypatch):
        from interface.cli import daemon as daemon_mod
        from unittest.mock import MagicMock

        observer = MagicMock()
        observer.is_alive.return_value = True

        def _sleep_raises(_seconds):
            raise KeyboardInterrupt

        monkeypatch.setattr(daemon_mod.time, "sleep", _sleep_raises)
        monkeypatch.setattr(daemon_mod, "start_heartbeat_thread", MagicMock())

        stop_fn = MagicMock()
        daemon_mod.run_watcher_with_crash_guard(
            create_fn=lambda: observer,
            stop_fn=stop_fn,
            watcher_path="/tmp/does-not-matter",
            session_id="test-session",
        )

        stop_fn.assert_called_once_with(observer)

    def test_stop_fn_exception_does_not_propagate(self, monkeypatch):
        """A broken stop_fn must not crash the shutdown path."""
        from interface.cli import daemon as daemon_mod
        from unittest.mock import MagicMock

        observer = MagicMock()
        observer.is_alive.return_value = True

        def _sleep_raises(_seconds):
            raise KeyboardInterrupt

        monkeypatch.setattr(daemon_mod.time, "sleep", _sleep_raises)
        monkeypatch.setattr(daemon_mod, "start_heartbeat_thread", MagicMock())

        stop_fn = MagicMock(side_effect=RuntimeError("boom"))
        daemon_mod.run_watcher_with_crash_guard(
            create_fn=lambda: observer,
            stop_fn=stop_fn,
            watcher_path="/tmp/does-not-matter",
            session_id="test-session",
        )  # must not raise

        stop_fn.assert_called_once_with(observer)
