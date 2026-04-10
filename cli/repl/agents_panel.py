# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
cli/repl/agents_panel.py — Sub-agent registry and Rich streaming panel.

Tracks active gRPC sub-agent sessions and renders them as a greyed-out
collapsible panel above the primary response in the REPL.

Usage (from shell.py)
---------------------
    from cli.repl.agents_panel import AgentRegistry, render_agents_panel

    registry = AgentRegistry()
    agent_id = registry.start("q_abc", "what does verify_token return?")
    # ... gRPC call fires asynchronously ...
    registry.finish(agent_id, result="HS256 on expiry returns None")
    render_agents_panel(registry)           # Rich panel (if available)
    registry.cancel(agent_id)              # /agents cancel <id>
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class AgentState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class SubAgent:
    """Represents one gRPC sub-agent call."""
    agent_id: str
    query: str
    state: AgentState = AgentState.PENDING
    result: str = ""
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    chunks: list[str] = field(default_factory=list)

    @property
    def elapsed(self) -> float:
        end = self.finished_at or time.time()
        return end - self.started_at

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "query": self.query,
            "state": self.state.value,
            "result": self.result,
            "error": self.error,
            "elapsed_s": round(self.elapsed, 2),
        }


class AgentRegistry:
    """Thread-safe registry of sub-agent sessions for one REPL turn."""

    def __init__(self) -> None:
        self._agents: dict[str, SubAgent] = {}
        self._lock = threading.Lock()

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self, query: str, agent_id: str | None = None) -> str:
        """Register a new sub-agent and mark it RUNNING. Returns agent_id."""
        aid = agent_id or str(uuid.uuid4())[:8]
        with self._lock:
            self._agents[aid] = SubAgent(
                agent_id=aid,
                query=query,
                state=AgentState.RUNNING,
            )
        return aid

    def append_chunk(self, agent_id: str, chunk: str) -> None:
        """Append a streaming chunk to a running agent."""
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent and agent.state == AgentState.RUNNING:
                agent.chunks.append(chunk)
                agent.result = "".join(agent.chunks)

    def finish(self, agent_id: str, result: str = "") -> None:
        """Mark agent as DONE with the final result."""
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent:
                agent.state = AgentState.DONE
                agent.result = result or agent.result
                agent.finished_at = time.time()

    def fail(self, agent_id: str, error: str) -> None:
        """Mark agent as FAILED."""
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent:
                agent.state = AgentState.FAILED
                agent.error = error
                agent.finished_at = time.time()

    def cancel(self, agent_id: str) -> bool:
        """Cancel a pending or running agent. Returns True if found."""
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent and agent.state in (AgentState.PENDING, AgentState.RUNNING):
                agent.state = AgentState.CANCELLED
                agent.finished_at = time.time()
                return True
        return False

    # ── queries ───────────────────────────────────────────────────────────────

    def all(self) -> list[SubAgent]:
        with self._lock:
            return list(self._agents.values())

    def active(self) -> list[SubAgent]:
        with self._lock:
            return [a for a in self._agents.values()
                    if a.state in (AgentState.PENDING, AgentState.RUNNING)]

    def get(self, agent_id: str) -> SubAgent | None:
        with self._lock:
            return self._agents.get(agent_id)

    def clear(self) -> None:
        """Remove all agents (call between REPL turns)."""
        with self._lock:
            self._agents.clear()

    def to_session_records(self) -> list[dict]:
        """Serialisable records for session persistence under sub_queries[]."""
        return [a.to_dict() for a in self.all()]


# ── Rich rendering ────────────────────────────────────────────────────────────

_STATE_ICON = {
    AgentState.PENDING:   "○",
    AgentState.RUNNING:   "◎",
    AgentState.DONE:      "✓",
    AgentState.FAILED:    "✗",
    AgentState.CANCELLED: "⊘",
}

_STATE_STYLE = {
    AgentState.PENDING:   "dim",
    AgentState.RUNNING:   "dim cyan",
    AgentState.DONE:      "dim green",
    AgentState.FAILED:    "dim red",
    AgentState.CANCELLED: "dim yellow",
}


def render_agents_panel(registry: AgentRegistry, max_result_chars: int = 120) -> None:
    """
    Print a greyed-out sub-agent panel using Rich (if available).
    Falls back to plain text when Rich is not installed.
    """
    agents = registry.all()
    if not agents:
        return

    try:
        from rich.console import Console  # pylint: disable=import-outside-toplevel
        from rich.panel import Panel       # pylint: disable=import-outside-toplevel
        from rich.text import Text         # pylint: disable=import-outside-toplevel

        console = Console(highlight=False)
        lines = Text()
        for agent in agents:
            icon = _STATE_ICON.get(agent.state, "?")
            style = _STATE_STYLE.get(agent.state, "dim")
            label = f"[{agent.agent_id}] {icon} {agent.query[:60]}"
            if agent.result:
                snippet = agent.result[:max_result_chars].replace("\n", " ")
                label += f"\n    → {snippet}"
            if agent.error:
                label += f"\n    ✗ {agent.error[:80]}"
            label += f"  ({agent.elapsed:.1f}s)\n"
            lines.append(label, style=style)

        console.print(
            Panel(lines, title="[dim]sub-agents[/dim]", border_style="dim", expand=False),
        )
    except ImportError:
        # Plain text fallback
        print("\n── sub-agents ──")
        for agent in agents:
            icon = _STATE_ICON.get(agent.state, "?")
            snippet = (agent.result or agent.error or "")[:80]
            print(f"  [{agent.agent_id}] {icon} {agent.query[:60]}  → {snippet}")
        print()


def stream_agents_panel(
    registry: AgentRegistry,
    refresh_fn: Callable[[], bool],
    fps: int = 10,
) -> None:
    """
    Use Rich ``Live`` to stream sub-agent updates at up to ``fps`` Hz.

    ``refresh_fn`` is called each frame; returns True to keep streaming.
    Stops when all agents are done or refresh_fn returns False.

    Throttled to ``fps`` (default 10) to avoid Rich tearing on fast streams.
    """
    try:
        from rich.console import Console  # pylint: disable=import-outside-toplevel
        from rich.live import Live         # pylint: disable=import-outside-toplevel
        from rich.panel import Panel       # pylint: disable=import-outside-toplevel
        from rich.text import Text         # pylint: disable=import-outside-toplevel

        console = Console(highlight=False)
        interval = 1.0 / fps

        def _build_renderable():
            lines = Text()
            for agent in registry.all():
                icon = _STATE_ICON.get(agent.state, "?")
                style = _STATE_STYLE.get(agent.state, "dim")
                label = f"[{agent.agent_id}] {icon} {agent.query[:60]}"
                if agent.result:
                    snippet = agent.result[:80].replace("\n", " ")
                    label += f"\n    → {snippet}"
                label += f"  ({agent.elapsed:.1f}s)\n"
                lines.append(label, style=style)
            return Panel(lines, title="[dim]sub-agents[/dim]", border_style="dim", expand=False)

        with Live(_build_renderable(), console=console, refresh_per_second=fps) as live:
            while refresh_fn():
                live.update(_build_renderable())
                time.sleep(interval)
                if not registry.active():
                    break

    except ImportError:
        # Rich not available — just render once at the end
        render_agents_panel(registry)
