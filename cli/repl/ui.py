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
from typing import Iterator


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

    @abstractmethod
    def banner(self, project_name: str, memory_count: int, graph_nodes: int,
               tier_summary: str, keys_present: list[str], multi_agent: bool) -> None:
        """Render the startup banner with project stats."""

    @abstractmethod
    def error_panel(self, message: str, detail: str = "") -> None:
        """Display an error as a styled panel — never show raw tracebacks."""

    def user_turn(self, query: str) -> None:
        """Display the user's query in the chat layout (default: no-op, handled by prompt)."""


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
        return input("  you ›  ")

    def tier_label(self, tier: str, model: str) -> None:
        print(f"\n  cognirepo ›  [{tier}]  {model}\n", flush=True)

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

    def banner(self, project_name: str, memory_count: int, graph_nodes: int,
               tier_summary: str, keys_present: list[str], multi_agent: bool) -> None:
        print("=" * 60)
        print("  c o g n i r e p o")
        print("=" * 60)
        print(f"  Project : {project_name}")
        print(f"  Index   : {memory_count} memories · {graph_nodes} graph nodes")
        print(f"  Tiers   : {tier_summary}")
        keys_str = ", ".join(keys_present) if keys_present else "none set — QUICK tier only"
        print(f"  API keys: {keys_str}")
        print(f"  Agents  : {'enabled (gRPC)' if multi_agent else 'disabled'}")
        print("  Type /help for commands · Ctrl+D or /exit to quit")
        print()

    def error_panel(self, message: str, detail: str = "") -> None:
        print(f"\n  [ERROR] {message}")
        if detail:
            print(f"  {detail}")
        print()


# ── rich UI ────────────────────────────────────────────────────────────────────

def _make_rich_heading() -> "Text":
    """
    Build a visually large 'cognirepo' heading using only Rich Text.
    Each letter is spaced out and painted with a magenta→cyan gradient
    so it reads as a prominent, styled title — no external font deps needed.
    """
    from rich.text import Text  # pylint: disable=import-outside-toplevel

    # Truecolor gradient: deep magenta → violet → bright cyan
    _GRADIENT = [
        "#e040fb", "#c94ff8", "#b25ef5", "#9b6df2",
        "#847def", "#6d8cec", "#569be9", "#3faae6",
        "#28b9e3",
    ]
    word = "cognirepo"
    heading = Text(justify="center")
    for i, ch in enumerate(word):
        color = _GRADIENT[i % len(_GRADIENT)]
        heading.append(ch, style=f"bold {color}")
        if i < len(word) - 1:
            heading.append("  ", style="")   # letter-spacing
    return heading


class RichUI(UI):
    """Rich + prompt_toolkit UI — used when [cli] extra is installed."""

    # Tier → colour mapping
    _TIER_COLORS = {
        "QUICK":    "bright_green",
        "STANDARD": "bright_blue",
        "COMPLEX":  "yellow",
        "EXPERT":   "bright_red",
    }

    def __init__(self) -> None:
        from rich.console import Console  # pylint: disable=import-outside-toplevel
        self._console = Console(highlight=False)
        self._history = None  # lazy-init FileHistory

    # ── core ───────────────────────────────────────────────────────────────────

    def print(self, text: str, end: str = "\n") -> None:
        self._console.print(text, end=end, markup=False, highlight=False)

    def prompt(self, ps: str = ">>> ") -> str:
        from prompt_toolkit import prompt as pt_prompt  # pylint: disable=import-outside-toplevel
        from prompt_toolkit.history import FileHistory  # pylint: disable=import-outside-toplevel
        from prompt_toolkit.styles import Style  # pylint: disable=import-outside-toplevel
        import os  # pylint: disable=import-outside-toplevel

        if self._history is None:
            history_path = os.path.expanduser("~/.cognirepo_history")
            try:
                self._history = FileHistory(history_path)
            except Exception:  # pylint: disable=broad-except
                from prompt_toolkit.history import InMemoryHistory  # pylint: disable=import-outside-toplevel
                self._history = InMemoryHistory()

        style = Style.from_dict({
            "prompt": "ansicyan bold",
        })
        return pt_prompt(
            [("class:prompt", "  you ›  ")],
            history=self._history,
            style=style,
        )

    def tier_label(self, tier: str, model: str) -> None:
        color = self._TIER_COLORS.get(tier, "white")
        short_model = model.split("/")[-1] if "/" in model else model
        self._console.print(
            f"\n  [dim]cognirepo[/dim] [bold {color}]›[/bold {color}]"
            f"  [{color}]{tier}[/{color}]  [dim]{short_model}[/dim]\n",
        )

    def stream_chunks(self, chunks: Iterator[str]) -> str:
        from rich.live import Live  # pylint: disable=import-outside-toplevel
        from rich.text import Text  # pylint: disable=import-outside-toplevel

        full: list[str] = []
        with Live(Text(""), refresh_per_second=12, console=self._console,
                  vertical_overflow="visible") as live:
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

    # ── new methods ────────────────────────────────────────────────────────────

    def banner(self, project_name: str, memory_count: int, graph_nodes: int,
               tier_summary: str, keys_present: list[str], multi_agent: bool) -> None:
        from rich.panel import Panel  # pylint: disable=import-outside-toplevel
        from rich.text import Text  # pylint: disable=import-outside-toplevel
        from rich.align import Align  # pylint: disable=import-outside-toplevel
        from rich.rule import Rule  # pylint: disable=import-outside-toplevel
        from rich import box  # pylint: disable=import-outside-toplevel

        heading = _make_rich_heading()

        keys_str = ", ".join(keys_present) if keys_present else "⚠  none set"
        agents_str = "enabled (gRPC)" if multi_agent else "disabled"

        stats = Text.assemble(
            (f"{memory_count}", "bold #28b9e3"), (" memories", "dim"),
            ("  ·  ", "dim"),
            (f"{graph_nodes}", "bold #28b9e3"), (" graph nodes", "dim"),
            ("  ·  ", "dim"),
            (f"{project_name}", "bold white"),
            "\n",
            ("API keys: ", "dim"), (keys_str, "green" if keys_present else "yellow"),
            ("  ·  agents: ", "dim"), (agents_str, "#28b9e3" if multi_agent else "dim"),
            "\n",
            ("Tiers: ", "dim"), (tier_summary, "dim"),
            justify="center",
        )

        hint = Text("/help for commands  ·  Ctrl+D or /exit to quit",
                    style="dim", justify="center")

        self._console.print(
            Panel(
                Align.center(
                    Text.assemble(
                        "\n",
                        heading,
                        "\n\n",
                        stats,
                        "\n\n",
                        hint,
                        "\n",
                    )
                ),
                border_style="#9b6df2",
                box=box.ROUNDED,
                padding=(0, 3),
            )
        )
        self._console.print()

    def error_panel(self, message: str, detail: str = "") -> None:
        from rich.panel import Panel  # pylint: disable=import-outside-toplevel
        from rich.text import Text  # pylint: disable=import-outside-toplevel
        from rich import box  # pylint: disable=import-outside-toplevel

        body = Text(message, style="bold red")
        if detail:
            body.append(f"\n\n{detail}", style="red")

        self._console.print(
            Panel(
                body,
                title="[bold red]  error  [/bold red]",
                border_style="red",
                box=box.ROUNDED,
                padding=(0, 2),
            )
        )
        self._console.print()


# ── auto-selector ──────────────────────────────────────────────────────────────

def make_ui() -> UI:
    """Return RichUI if rich + prompt_toolkit are installed, else StdlibUI."""
    try:
        import rich  # noqa: F401  # pylint: disable=import-outside-toplevel,unused-import
        import prompt_toolkit  # noqa: F401  # pylint: disable=import-outside-toplevel,unused-import
        return RichUI()
    except ImportError:
        return StdlibUI()
