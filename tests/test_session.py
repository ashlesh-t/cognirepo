# pylint: disable=missing-docstring, unnecessary-lambda, import-outside-toplevel, too-few-public-methods, duplicate-code
# pylint: disable=redefined-outer-name, unused-argument, broad-exception-caught, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tests/test_session.py — B4.2: conversation session management.

All tests are isolated to a tmp_path via monkeypatch so they never
touch the real .cognirepo/sessions/ directory.
"""
from __future__ import annotations

import json
import pytest


# ── fixture: redirect session storage to tmp_path ────────────────────────────

@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """
    Session isolation — conftest's isolated_cognirepo (autouse) already
    redirects set_cognirepo_dir() to tmp_path, so _sessions_dir() returns
    a tmp location automatically. Just patch load_max_exchanges here.
    """
    import orchestrator.session as _sess
    monkeypatch.setattr(_sess, "load_max_exchanges", lambda: 10)


# ── create / load ─────────────────────────────────────────────────────────────

class TestCreateLoad:
    def test_create_returns_session_dict(self):
        from orchestrator.session import create_session
        s = create_session()
        assert "session_id" in s
        assert isinstance(s["messages"], list)
        assert "created_at" in s

    def test_create_writes_json_file(self):
        import orchestrator.session as _sess
        from orchestrator.session import create_session
        s = create_session()
        path = _sess._sessions_dir() / f"{s['session_id']}.json"
        assert path.exists()

    def test_create_sets_current_pointer(self):
        import orchestrator.session as _sess
        from orchestrator.session import create_session
        s = create_session()
        assert _sess._current_ptr().exists()
        ptr = json.loads(_sess._current_ptr().read_text())
        assert ptr["session_id"] == s["session_id"]

    def test_load_session_returns_dict(self):
        from orchestrator.session import create_session, load_session
        s = create_session()
        loaded = load_session(s["session_id"])
        assert loaded is not None
        assert loaded["session_id"] == s["session_id"]

    def test_load_missing_session_returns_none(self):
        from orchestrator.session import load_session
        assert load_session("nonexistent-id") is None

    def test_load_current_session(self):
        from orchestrator.session import create_session, load_current_session
        s = create_session()
        cur = load_current_session()
        assert cur is not None
        assert cur["session_id"] == s["session_id"]

    def test_load_current_session_when_none_exists(self):
        from orchestrator.session import load_current_session
        assert load_current_session() is None

    def test_create_model_stored(self):
        from orchestrator.session import create_session, load_session
        s = create_session(model="gemini-2.0-flash")
        loaded = load_session(s["session_id"])
        assert loaded["model"] == "gemini-2.0-flash"


# ── find_session (prefix matching) ───────────────────────────────────────────

class TestFindSession:
    def test_exact_id_match(self):
        from orchestrator.session import create_session, find_session
        s = create_session()
        found = find_session(s["session_id"])
        assert found["session_id"] == s["session_id"]

    def test_prefix_match(self):
        from orchestrator.session import create_session, find_session
        s = create_session()
        prefix = s["session_id"][:8]
        found = find_session(prefix)
        assert found is not None
        assert found["session_id"] == s["session_id"]

    def test_ambiguous_prefix_returns_none(self):
        from orchestrator.session import create_session, find_session
        # Create two sessions
        create_session()
        create_session()
        # Single char prefix will match both
        found = find_session("")  # empty prefix matches everything
        assert found is None

    def test_nonexistent_prefix_returns_none(self):
        from orchestrator.session import find_session
        assert find_session("zzzzzzzzz") is None


# ── append_exchange / history cap ─────────────────────────────────────────────

class TestAppendExchange:
    def test_append_adds_two_messages(self):
        from orchestrator.session import create_session, append_exchange
        s = create_session()
        append_exchange(s, "hello?", "hi there", max_exchanges=10)
        assert len(s["messages"]) == 2
        assert s["messages"][0] == {"role": "user", "content": "hello?"}
        assert s["messages"][1] == {"role": "assistant", "content": "hi there"}

    def test_append_persists_to_disk(self):
        import orchestrator.session as _sess
        from orchestrator.session import create_session, append_exchange, load_session
        s = create_session()
        append_exchange(s, "q", "a", max_exchanges=10)
        loaded = load_session(s["session_id"])
        assert len(loaded["messages"]) == 2

    def test_second_exchange_accumulates(self):
        from orchestrator.session import create_session, append_exchange
        s = create_session()
        append_exchange(s, "q1", "a1", max_exchanges=10)
        append_exchange(s, "q2", "a2", max_exchanges=10)
        assert len(s["messages"]) == 4

    def test_history_capped_at_max_exchanges(self):
        """After 11 exchanges (cap=10), the oldest is dropped."""
        from orchestrator.session import create_session, append_exchange
        s = create_session()
        for i in range(11):
            append_exchange(s, f"user msg {i}", f"assistant msg {i}", max_exchanges=10)
        # 10 exchanges * 2 messages = 20 messages
        assert len(s["messages"]) == 20

    def test_oldest_exchange_dropped_on_overflow(self):
        """The 11th exchange drops exchange #0 (oldest)."""
        from orchestrator.session import create_session, append_exchange
        s = create_session()
        for i in range(10):
            append_exchange(s, f"question {i}", f"answer {i}", max_exchanges=10)
        # Now add the 11th — "question 0" / "answer 0" should be gone
        append_exchange(s, "question 10", "answer 10", max_exchanges=10)
        texts = [m["content"] for m in s["messages"]]
        assert "question 0" not in texts
        assert "answer 0" not in texts
        assert "question 1" in texts  # second oldest is now first

    def test_newest_messages_survive_trim(self):
        """Most recent exchanges are always preserved."""
        from orchestrator.session import create_session, append_exchange
        s = create_session()
        for i in range(12):
            append_exchange(s, f"q{i}", f"a{i}", max_exchanges=10)
        texts = [m["content"] for m in s["messages"]]
        assert "q11" in texts
        assert "a11" in texts
        assert "q10" in texts

    def test_cap_at_one_exchange(self):
        """max_exchanges=1 keeps only the most recent exchange."""
        from orchestrator.session import create_session, append_exchange
        s = create_session()
        append_exchange(s, "old q", "old a", max_exchanges=1)
        append_exchange(s, "new q", "new a", max_exchanges=1)
        assert len(s["messages"]) == 2
        assert s["messages"][0]["content"] == "new q"

    def test_messages_remain_balanced_after_trim(self):
        """After trimming, messages always come in user/assistant pairs."""
        from orchestrator.session import create_session, append_exchange
        s = create_session()
        for i in range(15):
            append_exchange(s, f"u{i}", f"a{i}", max_exchanges=10)
        assert len(s["messages"]) % 2 == 0
        for i in range(0, len(s["messages"]), 2):
            assert s["messages"][i]["role"] == "user"
            assert s["messages"][i + 1]["role"] == "assistant"


# ── list_sessions ─────────────────────────────────────────────────────────────

class TestListSessions:
    def test_empty_when_no_sessions(self):
        from orchestrator.session import list_sessions
        assert not list_sessions()

    def test_returns_created_sessions(self):
        from orchestrator.session import create_session, list_sessions
        create_session()
        create_session()
        sessions = list_sessions()
        assert len(sessions) == 2

    def test_sorted_newest_first(self):
        """Sessions are returned newest-first by created_at."""
        import time
        from orchestrator.session import create_session, list_sessions, append_exchange
        s1 = create_session()
        append_exchange(s1, "first q", "first a")
        time.sleep(0.01)  # ensure distinct timestamps
        s2 = create_session()
        append_exchange(s2, "second q", "second a")
        sessions = list_sessions()
        assert sessions[0]["session_id"] == s2["session_id"]
        assert sessions[1]["session_id"] == s1["session_id"]

    def test_limit_respected(self):
        from orchestrator.session import create_session, list_sessions
        for _ in range(5):
            create_session()
        assert len(list_sessions(limit=3)) == 3

    def test_no_limit_returns_all(self):
        from orchestrator.session import create_session, list_sessions
        for _ in range(5):
            create_session()
        assert len(list_sessions(limit=0)) == 5

    def test_current_session_pointer(self):
        from orchestrator.session import create_session, current_session_id
        s1 = create_session()
        assert current_session_id() == s1["session_id"]
        s2 = create_session()
        assert current_session_id() == s2["session_id"]


# ── messages_history in adapters ─────────────────────────────────────────────

class TestAdapterHistory:
    """Verify that conversation history is injected into adapter API calls."""

    def test_anthropic_history_in_messages(self, monkeypatch):
        monkeypatch.setattr("time.sleep", lambda _: None)
        from unittest.mock import MagicMock, patch

        captured_kwargs = {}
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="pong")]
        mock_response.usage.input_tokens = 5
        mock_response.usage.output_tokens = 2

        def capture_create(**kwargs):
            captured_kwargs.update(kwargs)
            return mock_response

        mock_client.messages.create.side_effect = capture_create

        history = [
            {"role": "user", "content": "prev question"},
            {"role": "assistant", "content": "prev answer"},
        ]

        with patch("anthropic.Anthropic", return_value=mock_client):
            from orchestrator.model_adapters import anthropic_adapter
            anthropic_adapter.call("current q", "system", [], messages_history=history)

        sent_messages = captured_kwargs["messages"]
        assert sent_messages[0] == {"role": "user", "content": "prev question"}
        assert sent_messages[1] == {"role": "assistant", "content": "prev answer"}
        assert sent_messages[2] == {"role": "user", "content": "current q"}

    def test_openai_history_after_system_message(self, monkeypatch):
        monkeypatch.setattr("time.sleep", lambda _: None)
        from unittest.mock import MagicMock, patch

        captured_msgs = []
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "pong"
        mock_response.choices[0].message.tool_calls = None
        mock_response.usage.prompt_tokens = 5
        mock_response.usage.completion_tokens = 2

        def capture_create(**kwargs):
            captured_msgs.extend(kwargs["messages"])
            return mock_response

        mock_client.chat.completions.create.side_effect = capture_create

        history = [
            {"role": "user", "content": "prev q"},
            {"role": "assistant", "content": "prev a"},
        ]

        with patch("openai.OpenAI", return_value=mock_client):
            from orchestrator.model_adapters import openai_adapter
            openai_adapter.call("now q", "system text", [], messages_history=history)

        assert captured_msgs[0]["role"] == "system"
        assert captured_msgs[1] == {"role": "user", "content": "prev q"}
        assert captured_msgs[2] == {"role": "assistant", "content": "prev a"}
        assert captured_msgs[3] == {"role": "user", "content": "now q"}

    def test_gemini_history_converts_assistant_to_model(self):
        from orchestrator.model_adapters.gemini_adapter import _build_contents

        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        contents = _build_contents("follow-up", history)

        assert isinstance(contents, list)
        assert contents[0] == {"role": "user", "parts": [{"text": "hello"}]}
        assert contents[1] == {"role": "model", "parts": [{"text": "hi"}]}
        assert contents[2] == {"role": "user", "parts": [{"text": "follow-up"}]}

    def test_gemini_no_history_returns_string(self):
        from orchestrator.model_adapters.gemini_adapter import _build_contents
        assert _build_contents("simple question", None) == "simple question"
        assert _build_contents("simple question", []) == "simple question"
