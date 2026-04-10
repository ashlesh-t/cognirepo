# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""Tests for cli/repl/ui.py and cli/repl/commands.py."""
import sys
import types

import pytest

from cli.repl.ui import StdlibUI, make_ui, UI
from cli.repl.commands import dispatch, list_commands


# ── StdlibUI ──────────────────────────────────────────────────────────────────

class _CaptureUI(StdlibUI):
    """StdlibUI subclass that captures output instead of printing."""
    def __init__(self):
        self._output: list[str] = []

    def print(self, text: str, end: str = "\n") -> None:
        self._output.append(text)

    def status(self, text: str) -> None:
        self._output.append(text)

    def tier_label(self, tier: str, model: str) -> None:
        self._output.append(f"[{tier} → {model}]")

    def stream_chunks(self, chunks) -> str:
        parts = list(chunks)
        text = "".join(parts)
        self._output.append(text)
        return text

    def spinner(self, message: str):
        from cli.repl.ui import _NullSpinner
        return _NullSpinner()


def test_stdlib_ui_print_captures():
    ui = _CaptureUI()
    ui.print("hello world")
    assert "hello world" in ui._output


def test_stdlib_ui_tier_label():
    ui = _CaptureUI()
    ui.tier_label("QUICK", "local")
    assert any("QUICK" in s for s in ui._output)


def test_stdlib_ui_stream_chunks():
    ui = _CaptureUI()
    result = ui.stream_chunks(iter(["hello", " ", "world"]))
    assert result == "hello world"


# ── make_ui falls back to StdlibUI when rich not present ──────────────────────

def test_make_ui_fallback_to_stdlib(monkeypatch):
    """When rich/prompt_toolkit are unavailable, make_ui must return StdlibUI."""
    import builtins
    real_import = builtins.__import__

    def _block_rich(name, *args, **kwargs):
        if name in ("rich", "prompt_toolkit"):
            raise ImportError(f"blocked: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_rich)
    ui = make_ui()
    assert isinstance(ui, StdlibUI)


# ── slash command registry ────────────────────────────────────────────────────

def test_list_commands_not_empty():
    cmds = list_commands()
    assert len(cmds) > 0
    names = [c[0] for c in cmds]
    assert "help" in names
    assert "clear" in names
    assert "status" in names


def test_dispatch_unknown_command():
    ui = _CaptureUI()
    state: dict = {}
    result = dispatch("nonexistent_cmd_xyz", "", ui, state)
    assert result is True  # REPL continues
    assert any("Unknown" in s for s in ui._output)


def test_dispatch_clear_resets_history():
    ui = _CaptureUI()
    state = {"messages_history": [{"role": "user", "content": "hello"}]}
    result = dispatch("clear", "", ui, state)
    assert result is True
    assert state["messages_history"] == []


def test_dispatch_exit_returns_false():
    ui = _CaptureUI()
    state: dict = {}
    result = dispatch("exit", "", ui, state)
    assert result is False


def test_dispatch_model_set():
    ui = _CaptureUI()
    state: dict = {}
    dispatch("model", "set claude-opus-4-6", ui, state)
    assert state.get("force_model") == "claude-opus-4-6"


def test_dispatch_history_empty():
    ui = _CaptureUI()
    state = {"messages_history": []}
    dispatch("history", "", ui, state)
    assert any("no history" in s.lower() for s in ui._output)
