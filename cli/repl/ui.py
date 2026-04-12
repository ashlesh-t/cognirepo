# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Abstract UI interface with two implementations:

RichUI    — uses rich + prompt_toolkit for colours, spinners, streaming markdown
StdlibUI  — fallback; uses readline + print; identical to the original repl.py

Auto-selected at import time based on whether rich imports successfully.
Import prompt_toolkit only inside RichUI to avoid readline conflicts.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator, Optional


# ── abstract base ──────────────────────────────────────────────────────────────

class UI(ABC):
    """Base interface all UI implementations must satisfy."""

    @abstractmethod
    def print(self, text: str, end: str = "\n") -> None:
        """Print a plain line."""

    @abstractmethod
    def prompt(self, ps: str = ">>> ") -> str:
        """Read one line of input; raises EOFError on Ctrl+D."""

    @abstractmethod
    def tier_label(self, tier: str, model: str) -> None:
        """Print the tier/model badge before streaming output."""

    @abstractmethod
    def stream_chunks(self, chunks: Iterator[str]) -> str:
        """Consume a streaming chunk iterator, display live, return full text."""

    @abstractmethod
    def spinner(self, message: str):
        """Context manager: show a spinner while work is in progress."""

    @abstractmethod
    def status(self, text: str) -> None:
        """Print a status/info line (muted)."""


# ── stdlib UI (original behaviour, no extra deps) ─────────────────────────────

class _NullSpinner:
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass


class StdlibUI(UI):
    """Plain readline + print UI — always available, no extra deps."""

    def print(self, text: str, end: str = "\n") -> None:
        print(text, end=end, flush=True)

    def prompt(self, ps: str = ">>> ") -> str:
        return input(ps)

    def tier_label(self, tier: str, model: str) -> None:
        print(f"[{tier} → {model}] ", end="", flush=True)

    def stream_chunks(self, chunks: Iterator[str]) -> str:
        full: list[str] = []
        for chunk in chunks:
            print(chunk, end="", flush=True)
            full.append(chunk)
        print()
        return "".join(full)

    def spinner(self, message: str):
        print(f"  {message}…", flush=True)
        return _NullSpinner()

    def status(self, text: str) -> None:
        print(f"  {text}", flush=True)


# ── rich UI ────────────────────────────────────────────────────────────────────

class RichUI(UI):
    """Rich + prompt_toolkit UI — used when [cli] extra is installed."""

    def __init__(self) -> None:
        from rich.console import Console  # pylint: disable=import-outside-toplevel
        self._console = Console(highlight=False)

    def print(self, text: str, end: str = "\n") -> None:
        self._console.print(text, end=end)

    def prompt(self, ps: str = ">>> ") -> str:
        from prompt_toolkit import prompt as pt_prompt  # pylint: disable=import-outside-toplevel
        from prompt_toolkit.history import InMemoryHistory  # pylint: disable=import-outside-toplevel
        if not hasattr(self, "_history"):
            self._history = InMemoryHistory()  # pylint: disable=attribute-defined-outside-init
        return pt_prompt(ps, history=self._history)

    def tier_label(self, tier: str, model: str) -> None:
        _TIER_COLORS = {
            "QUICK":    "green",
            "STANDARD": "blue",
            "COMPLEX":  "yellow",
            "EXPERT":   "red",
        }
        color = _TIER_COLORS.get(tier, "white")
        self._console.print(
            f"[bold {color}][{tier} → {model}][/bold {color}] ",
            end="",
        )

    def stream_chunks(self, chunks: Iterator[str]) -> str:
        from rich.live import Live  # pylint: disable=import-outside-toplevel
        from rich.text import Text  # pylint: disable=import-outside-toplevel

        full: list[str] = []
        with Live(Text(""), refresh_per_second=10, console=self._console) as live:
            for chunk in chunks:
                full.append(chunk)
                live.update(Text("".join(full)))
        self._console.print()
        return "".join(full)

    def spinner(self, message: str):
        from rich.spinner import Spinner  # pylint: disable=import-outside-toplevel
        from rich.live import Live  # pylint: disable=import-outside-toplevel
        return Live(Spinner("dots", text=message), console=self._console, refresh_per_second=10)

    def status(self, text: str) -> None:
        self._console.print(f"[dim]  {text}[/dim]")


# ── auto-selector ──────────────────────────────────────────────────────────────

def make_ui() -> UI:
    """Return RichUI if rich + prompt_toolkit are installed, else StdlibUI."""
    try:
        import rich  # noqa: F401  # pylint: disable=import-outside-toplevel,unused-import
        import prompt_toolkit  # noqa: F401  # pylint: disable=import-outside-toplevel,unused-import
        return RichUI()
    except ImportError:
        return StdlibUI()
