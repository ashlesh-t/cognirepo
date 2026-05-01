# pylint: disable=missing-docstring, unnecessary-lambda, import-outside-toplevel, too-few-public-methods, duplicate-code
# pylint: disable=redefined-outer-name, unused-argument, broad-exception-caught, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_router.py — B4.4: local resolver pattern matching tests.

All external calls (AST index, graph, episodic memory) are mocked so no
real index files are needed.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import orchestrator.router


# ── helpers ───────────────────────────────────────────────────────────────────

def _bundle():
    b = MagicMock()
    b.ast_hits = []
    return b


def _resolve(query: str, bundle=None) -> str | None:
    # Use the function already in memory
    return orchestrator.router.try_local_resolve(query, bundle or _bundle())


# ── "where is <symbol>" ───────────────────────────────────────────────────────

class TestWhereIs:
    def test_basic(self):
        with patch("orchestrator.router._lookup_symbol", return_value="found") as m:
            result = _resolve("where is verify_token")
            assert m.called, "Expected _lookup_symbol to be called"
            assert result == "found"

    def test_with_question_mark(self):
        with patch("orchestrator.router._lookup_symbol", return_value="found") as m:
            _resolve("where is foo?")
            assert m.called

    def test_where_can_i_find(self):
        with patch("orchestrator.router._lookup_symbol", return_value="found") as m:
            _resolve("where can i find verify_token?")
            assert m.called

    def test_lookup_none_falls_through(self):
        with patch("orchestrator.router._lookup_symbol", return_value=None):
            assert _resolve("where is nonexistent") is None


# ── "who calls <function>" ────────────────────────────────────────────────────

class TestWhoCalls:
    def test_basic(self):
        with patch("orchestrator.router._who_calls", return_value="callers: main") as m:
            result = _resolve("who calls route_query")
            assert m.called
            assert result == "callers: main"

    def test_with_question_mark(self):
        with patch("orchestrator.router._who_calls", return_value="callers") as m:
            _resolve("who calls foo?")
            assert m.called

    def test_who_calls_none_falls_through(self):
        with patch("orchestrator.router._who_calls", return_value=None):
            assert _resolve("who calls nonexistent") is None


# ── "list files" / "what files" ───────────────────────────────────────────────

class TestListFiles:
    def test_list_files(self):
        with patch("orchestrator.router._list_files", return_value="file1.py") as m:
            _resolve("list files")
            assert m.called

    def test_what_files(self):
        with patch("orchestrator.router._list_files", return_value="files") as m:
            _resolve("what files are indexed?")
            assert m.called

    def test_show_files(self):
        with patch("orchestrator.router._list_files", return_value="files") as m:
            _resolve("show files")
            assert m.called

    def test_list_files_none_falls_through(self):
        with patch("orchestrator.router._list_files", return_value=None):
            assert _resolve("list files") is None


# ── "graph stats" ─────────────────────────────────────────────────────────────

class TestGraphStats:
    def test_graph_stats(self):
        with patch("orchestrator.router._graph_stats", return_value="10 nodes") as m:
            _resolve("graph stats")
            assert m.called

    def test_how_many_nodes(self):
        with patch("orchestrator.router._graph_stats", return_value="10 nodes") as m:
            _resolve("how many nodes?")
            assert m.called

    def test_graph_size(self):
        with patch("orchestrator.router._graph_stats", return_value="10 nodes") as m:
            _resolve("graph size")
            assert m.called


# ── "recent history" ──────────────────────────────────────────────────────────

class TestRecentHistory:
    def test_recent_history(self):
        with patch("orchestrator.router._recent_history", return_value="3 events") as m:
            _resolve("recent history")
            assert m.called

    def test_what_did_i_do(self):
        with patch("orchestrator.router._recent_history", return_value="events") as m:
            _resolve("what did i do")
            assert m.called

    def test_show_history(self):
        with patch("orchestrator.router._recent_history", return_value="events") as m:
            _resolve("show history")
            assert m.called


# ── unrecognised queries fall through ─────────────────────────────────────────

class TestFallthrough:
    def test_complex_reasoning_query(self):
        assert _resolve("why is JWT verify failing?") is None

    def test_architectural_query(self):
        assert _resolve("explain the architecture of the auth module") is None

    def test_greeting(self):
        assert _resolve("hello") is None

    def test_unrelated_question(self):
        assert _resolve("what time is it?") is None
