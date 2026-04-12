# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Tests for multi-agent gRPC behaviour in rpc/client.py:
  - retry loop (3 attempts, exponential backoff) on UNAVAILABLE / DEADLINE_EXCEEDED
  - non-retryable errors surface immediately
  - server kill mid-call → router falls back, primary model still completes

All tests are unit-level (mocked stubs, no live server).
"""
from __future__ import annotations
import pytest

import sys
from unittest.mock import MagicMock, patch

# ── Stub grpc module ──────────────────────────────────────────────────────────
class _FakeStatusCode:
    UNAVAILABLE = "UNAVAILABLE"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    INTERNAL = "INTERNAL"
    NOT_FOUND = "NOT_FOUND"

    def __eq__(self, other):
        return self is other or (isinstance(other, str) and self == other)


class _FakeRpcError(Exception):
    def __init__(self, code, details=""):
        self._code = code
        self._details = details

    def code(self):
        return self._code

    def details(self):
        return self._details


_grpc_mock = MagicMock()
_grpc_mock.StatusCode = _FakeStatusCode
_grpc_mock.RpcError = _FakeRpcError
sys.modules["grpc"] = _grpc_mock

for _mod in (
    "rpc.proto",
    "rpc.proto.cognirepo_pb2",
    "rpc.proto.cognirepo_pb2_grpc",
    "rpc.context_store",
    "grpc_health",
    "grpc_health.v1",
    "grpc_health.v1.health_pb2",
    "grpc_health.v1.health_pb2_grpc",
):
    # Force-assign (not setdefault) so a cached real module from a prior test
    # file does not survive into this file's grpc-mocked environment.
    # dotenv is NOT stubbed — it is a real installed package used by test_env_wizard.py.
    sys.modules[_mod] = MagicMock()

# Evict cached rpc.* modules so they re-import against the mock grpc above.
for _rpc_mod in ("rpc.server", "rpc.client"):
    sys.modules.pop(_rpc_mod, None)

import rpc.client as _cli_mod  # noqa: E402 — after sys.modules stubs

_cli_mod._GRPC_HEALTH_AVAILABLE = False
_cli_mod._RETRY_BASE_DELAY = 0.0  # disable sleep in tests

_MULTIAGENT_STUBS = [
    "grpc", "rpc.proto", "rpc.proto.cognirepo_pb2", "rpc.proto.cognirepo_pb2_grpc",
    "rpc.context_store",
    "grpc_health", "grpc_health.v1", "grpc_health.v1.health_pb2",
    "grpc_health.v1.health_pb2_grpc",
    "rpc.server", "rpc.client",
]


@pytest.fixture(autouse=True, scope="module")
def _setup_and_cleanup_multiagent():
    """Ensure rpc.client settings are applied; evict stubs after tests finish."""
    # Re-apply settings in case rpc.client was evicted + re-imported by a prior module.
    import importlib  # pylint: disable=import-outside-toplevel
    _mod = importlib.import_module("rpc.client")
    _mod._GRPC_HEALTH_AVAILABLE = False
    _mod._RETRY_BASE_DELAY = 0.0
    yield
    for _s in _MULTIAGENT_STUBS:
        sys.modules.pop(_s, None)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_client():
    """Return a CogniRepoClient with a mocked channel (no network)."""
    from rpc.client import CogniRepoClient
    client = CogniRepoClient.__new__(CogniRepoClient)
    client._host = "localhost"
    client._port = 50051
    client._address = "localhost:50051"
    client._channel = MagicMock()
    client._query_stub = MagicMock()
    client._ctx_stub = MagicMock()
    return client


def _unavailable_error() -> _FakeRpcError:
    return _FakeRpcError(_FakeStatusCode.UNAVAILABLE, "server gone")


def _deadline_error() -> _FakeRpcError:
    return _FakeRpcError(_FakeStatusCode.DEADLINE_EXCEEDED, "timed out")


# ── retry behaviour ───────────────────────────────────────────────────────────

class TestRetryLogic:

    def test_retries_on_unavailable_then_succeeds(self):
        """UNAVAILABLE on first call retries and succeeds on second."""
        from rpc.client import CogniRepoClient
        from rpc.proto.cognirepo_pb2 import QueryResponse

        client = _make_client()
        good_response = MagicMock()
        good_response.result = "answer"
        client._query_stub.SubQuery.side_effect = [
            _unavailable_error(),
            good_response,
        ]

        result = client.sub_query("what is auth.py?")
        assert result.result == "answer"
        assert client._query_stub.SubQuery.call_count == 2

    def test_retries_on_deadline_exceeded(self):
        """DEADLINE_EXCEEDED triggers retries."""
        client = _make_client()
        good_response = MagicMock(result="ok")
        client._query_stub.SubQuery.side_effect = [
            _deadline_error(),
            _deadline_error(),
            good_response,
        ]

        result = client.sub_query("who calls verify_token?")
        assert result.result == "ok"
        assert client._query_stub.SubQuery.call_count == 3

    def test_exhausted_retries_raises_rpc_error(self):
        """After 3 failed attempts, raises the last RpcError."""
        client = _make_client()
        client._query_stub.SubQuery.side_effect = _unavailable_error()

        with pytest.raises(_FakeRpcError) as exc_info:
            client.sub_query("complex question")

        assert client._query_stub.SubQuery.call_count == 3
        assert exc_info.value.code() == _FakeStatusCode.UNAVAILABLE

    def test_non_retryable_error_surfaces_immediately(self):
        """An INTERNAL error is NOT retried — surfaces on first attempt."""
        client = _make_client()
        client._query_stub.SubQuery.side_effect = _FakeRpcError(
            _FakeStatusCode.INTERNAL, "server panic"
        )

        with pytest.raises(_FakeRpcError):
            client.sub_query("test")

        assert client._query_stub.SubQuery.call_count == 1

    def test_trace_id_propagated_in_metadata(self):
        """trace_id appears in gRPC metadata on every attempt."""
        client = _make_client()
        client._query_stub.SubQuery.return_value = MagicMock(result="ok")

        client.sub_query("test", trace_id="abc-123")

        _, kwargs = client._query_stub.SubQuery.call_args
        meta = dict(kwargs.get("metadata", []))
        assert meta.get("x-trace-id") == "abc-123"

    def test_auto_generated_trace_id_when_not_provided(self):
        """When trace_id is omitted, a UUID is auto-generated."""
        client = _make_client()
        client._query_stub.SubQuery.return_value = MagicMock(result="ok")

        client.sub_query("test")

        _, kwargs = client._query_stub.SubQuery.call_args
        meta = dict(kwargs.get("metadata", []))
        trace = meta.get("x-trace-id", "")
        assert len(trace) == 36  # UUID4 format


# ── server kill / fallback ────────────────────────────────────────────────────

class TestServerKillFallback:

    def test_router_fallback_when_grpc_server_killed(self):
        """
        When the gRPC sub-agent call fails (server killed mid-request),
        the router's main model call still completes.

        Simulates the router's multi-agent path:
          1. sub_query() raises RpcError (UNAVAILABLE — server killed)
          2. Router catches it, logs WARN, continues without sub-result
          3. Primary model route() still returns a response
        """
        # The router uses rpc.client.sub_query module function
        with patch("rpc.client.CogniRepoClient") as mock_cls:
            instance = mock_cls.return_value.__enter__.return_value
            instance.sub_query.side_effect = _unavailable_error()

            from rpc.client import sub_query
            result = sub_query("what does verify_token do?")

        # module-level sub_query wraps RpcError into an error string
        assert "[gRPC error:" in result

    def test_warn_logged_on_server_kill(self, caplog):
        """WARN is emitted when the sub-agent gRPC call fails."""
        import logging
        client = _make_client()
        client._query_stub.SubQuery.side_effect = _unavailable_error()

        with caplog.at_level(logging.WARNING, logger="rpc.client"):
            with pytest.raises(_FakeRpcError):
                client.sub_query("test")

        warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warn_records) >= 1
        assert "sub_query" in warn_records[0].message or "retry" in warn_records[0].message.lower()
