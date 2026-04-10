# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""Tests for cli/repl/agents_panel.py — AgentRegistry and rendering helpers."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from cli.repl.agents_panel import (
    AgentRegistry,
    AgentState,
    SubAgent,
    render_agents_panel,
)


# ── AgentRegistry ─────────────────────────────────────────────────────────────

class TestAgentRegistry:

    def test_start_creates_running_agent(self):
        reg = AgentRegistry()
        aid = reg.start("what is auth.py?")
        agent = reg.get(aid)
        assert agent is not None
        assert agent.state == AgentState.RUNNING
        assert agent.query == "what is auth.py?"

    def test_start_with_explicit_id(self):
        reg = AgentRegistry()
        aid = reg.start("test query", agent_id="abc123")
        assert aid == "abc123"
        assert reg.get("abc123") is not None

    def test_finish_sets_done_state(self):
        reg = AgentRegistry()
        aid = reg.start("q")
        reg.finish(aid, result="the answer")
        agent = reg.get(aid)
        assert agent.state == AgentState.DONE
        assert agent.result == "the answer"
        assert agent.finished_at is not None

    def test_fail_sets_failed_state(self):
        reg = AgentRegistry()
        aid = reg.start("q")
        reg.fail(aid, error="timeout")
        agent = reg.get(aid)
        assert agent.state == AgentState.FAILED
        assert agent.error == "timeout"

    def test_cancel_pending_agent(self):
        reg = AgentRegistry()
        aid = reg.start("q")
        result = reg.cancel(aid)
        assert result is True
        assert reg.get(aid).state == AgentState.CANCELLED

    def test_cancel_done_agent_returns_false(self):
        reg = AgentRegistry()
        aid = reg.start("q")
        reg.finish(aid, result="done")
        assert reg.cancel(aid) is False

    def test_cancel_unknown_agent_returns_false(self):
        reg = AgentRegistry()
        assert reg.cancel("nonexistent") is False

    def test_append_chunk_accumulates(self):
        reg = AgentRegistry()
        aid = reg.start("q")
        reg.append_chunk(aid, "hello ")
        reg.append_chunk(aid, "world")
        assert reg.get(aid).result == "hello world"

    def test_active_returns_only_running(self):
        reg = AgentRegistry()
        a1 = reg.start("q1")
        a2 = reg.start("q2")
        reg.finish(a1, result="done")
        active = reg.active()
        assert len(active) == 1
        assert active[0].agent_id == a2

    def test_all_returns_all_agents(self):
        reg = AgentRegistry()
        reg.start("q1")
        reg.start("q2")
        assert len(reg.all()) == 2

    def test_clear_removes_all(self):
        reg = AgentRegistry()
        reg.start("q1")
        reg.start("q2")
        reg.clear()
        assert reg.all() == []

    def test_to_session_records_serialisable(self):
        reg = AgentRegistry()
        aid = reg.start("find verify_token")
        reg.finish(aid, result="found in auth.py:10")
        records = reg.to_session_records()
        assert len(records) == 1
        r = records[0]
        assert r["state"] == "done"
        assert r["result"] == "found in auth.py:10"
        assert "elapsed_s" in r

    def test_elapsed_increases_while_running(self):
        reg = AgentRegistry()
        aid = reg.start("q")
        time.sleep(0.05)
        assert reg.get(aid).elapsed >= 0.04

    def test_elapsed_frozen_after_finish(self):
        reg = AgentRegistry()
        aid = reg.start("q")
        time.sleep(0.05)
        reg.finish(aid, result="done")
        elapsed_at_finish = reg.get(aid).elapsed
        time.sleep(0.05)
        assert reg.get(aid).elapsed == pytest.approx(elapsed_at_finish, abs=0.01)


# ── render_agents_panel ───────────────────────────────────────────────────────

class TestRenderAgentsPanel:

    def test_render_empty_registry_produces_no_output(self, capsys):
        reg = AgentRegistry()
        render_agents_panel(reg)
        out = capsys.readouterr().out
        assert out == ""

    def test_render_plain_fallback_when_rich_missing(self, capsys):
        reg = AgentRegistry()
        aid = reg.start("what does verify_token do?")
        reg.finish(aid, result="returns None on expiry")

        with patch.dict("sys.modules", {"rich": None, "rich.console": None,
                                         "rich.panel": None, "rich.text": None}):
            render_agents_panel(reg)

        out = capsys.readouterr().out
        assert "sub-agent" in out
        assert "verify_token" in out

    def test_render_with_failed_agent(self, capsys):
        reg = AgentRegistry()
        aid = reg.start("complex query")
        reg.fail(aid, error="connection refused")

        with patch.dict("sys.modules", {"rich": None, "rich.console": None,
                                         "rich.panel": None, "rich.text": None}):
            render_agents_panel(reg)

        out = capsys.readouterr().out
        assert "complex query" in out


# ── /agents command integration ───────────────────────────────────────────────

class TestAgentsCommand:

    def _make_state(self, registry):
        return {"agent_registry": registry}

    def _make_ui(self):
        ui = MagicMock()
        ui.print = MagicMock()
        ui.status = MagicMock()
        return ui

    def test_agents_command_lists_agents(self, monkeypatch):
        monkeypatch.setenv("COGNIREPO_MULTI_AGENT_ENABLED", "true")
        from cli.repl.commands import _REGISTRY
        _, handler = _REGISTRY["agents"]

        reg = AgentRegistry()
        aid = reg.start("who calls verify_token?")
        reg.finish(aid, result="router.py:42")

        ui = self._make_ui()
        state = self._make_state(reg)
        result = handler(ui, "", state)

        assert result is True
        printed = " ".join(str(c) for c in ui.print.call_args_list)
        assert "verify_token" in printed

    def test_agents_command_cancel(self, monkeypatch):
        monkeypatch.setenv("COGNIREPO_MULTI_AGENT_ENABLED", "true")
        from cli.repl.commands import _REGISTRY
        _, handler = _REGISTRY["agents"]

        reg = AgentRegistry()
        aid = reg.start("some query")

        ui = self._make_ui()
        state = self._make_state(reg)
        handler(ui, f"cancel {aid}", state)

        assert reg.get(aid).state == AgentState.CANCELLED

    def test_agents_command_disabled_when_multi_agent_off(self, monkeypatch):
        monkeypatch.setenv("COGNIREPO_MULTI_AGENT_ENABLED", "false")
        from cli.repl.commands import _REGISTRY
        _, handler = _REGISTRY["agents"]

        ui = self._make_ui()
        handler(ui, "", {})

        printed = " ".join(str(c) for c in ui.print.call_args_list)
        assert "disabled" in printed.lower()
