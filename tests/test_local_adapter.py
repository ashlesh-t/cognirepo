# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Tests for orchestrator/model_adapters/local_adapter.py."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# Stub heavy deps — try real import first; only stub if the package is absent.
_LOCAL_ADAPTER_STUBS: list[str] = []
for _dep in ("faiss", "fastembed"):
    try:
        __import__(_dep)
    except ImportError:
        sys.modules[_dep] = MagicMock()
        _LOCAL_ADAPTER_STUBS.append(_dep)
try:
    __import__("networkx")
except ImportError:
    _nx_stub = MagicMock()
    _nx_stub.DiGraph = MagicMock(return_value=MagicMock())
    sys.modules["networkx"] = _nx_stub
    _LOCAL_ADAPTER_STUBS.append("networkx")


@pytest.fixture(autouse=True, scope="module")
def _cleanup_local_adapter_stubs():
    yield
    for _mod in _LOCAL_ADAPTER_STUBS:
        sys.modules.pop(_mod, None)

from orchestrator.model_adapters.local_adapter import call, NoLocalAnswer, _resolve_locally


# ── _resolve_locally ──────────────────────────────────────────────────────────

def test_resolve_locally_returns_pattern_answer():
    """Pattern matcher (try_local_resolve) provides an answer."""
    with patch("orchestrator.router.try_local_resolve", return_value="Found at auth.py:10"):
        result = _resolve_locally("where is verify_token")
    assert result == "Found at auth.py:10"


def test_resolve_locally_falls_through_to_docs():
    """Pattern matcher returns None, docs index answers."""
    mock_idx = MagicMock()
    mock_idx.is_docs_query.return_value = True
    mock_idx.answer.return_value = [{"score": 0.9, "text": "Install with pip.", "file": "USAGE.md", "section": "Install"}]

    with (
        patch("orchestrator.router.try_local_resolve", return_value=None),
        patch("cli.docs_index.ensure_docs_index", return_value=mock_idx),
    ):
        result = _resolve_locally("how do I install cognirepo")

    assert result is not None
    assert "Install with pip." in result
    assert "→ see:" in result


def test_resolve_locally_returns_none_when_all_fail():
    mock_idx = MagicMock()
    mock_idx.is_docs_query.return_value = False

    with (
        patch("orchestrator.router.try_local_resolve", return_value=None),
        patch("cli.docs_index.ensure_docs_index", return_value=mock_idx),
    ):
        result = _resolve_locally("design a distributed system")

    assert result is None


def test_resolve_locally_handles_exception_gracefully():
    with (
        patch("orchestrator.router.try_local_resolve", side_effect=RuntimeError("boom")),
        patch("cli.docs_index.ensure_docs_index", side_effect=RuntimeError("boom2")),
    ):
        result = _resolve_locally("any query")
    assert result is None


# ── call() — non-streaming ────────────────────────────────────────────────────

def test_call_returns_model_response_when_answer_found():
    with patch(
        "orchestrator.model_adapters.local_adapter._resolve_locally",
        return_value="This is the answer.",
    ):
        resp = call("test query")
    assert resp.text == "This is the answer."
    assert resp.provider == "local"
    assert resp.model == "local-resolver"


def test_call_raises_no_local_answer_when_nothing_found():
    with patch(
        "orchestrator.model_adapters.local_adapter._resolve_locally",
        return_value=None,
    ):
        with pytest.raises(NoLocalAnswer):
            call("something complex")


# ── call() — streaming ────────────────────────────────────────────────────────

def test_call_stream_yields_answer():
    with patch(
        "orchestrator.model_adapters.local_adapter._resolve_locally",
        return_value="Streaming answer.",
    ):
        chunks = list(call("test query", stream=True))
    assert chunks == ["Streaming answer."]


def test_call_stream_raises_no_local_answer():
    with patch(
        "orchestrator.model_adapters.local_adapter._resolve_locally",
        return_value=None,
    ):
        with pytest.raises(NoLocalAnswer):
            list(call("complex query", stream=True))


# ── provider label ────────────────────────────────────────────────────────────

def test_call_provider_is_local():
    with patch(
        "orchestrator.model_adapters.local_adapter._resolve_locally",
        return_value="answer",
    ):
        resp = call("q")
    assert resp.provider == "local"
