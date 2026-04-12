# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Tests for the gRPC HealthServicer in rpc/server.py and the health()
client method in rpc/client.py.

All tests are unit-level — no live gRPC server is started.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# ── Stub grpc and proto modules so no network / grpcio install needed ─────────
_grpc_mock = MagicMock()
_grpc_mock.__version__ = "1.60.0"  # grpc_health.v1.health_pb2_grpc reads grpc.__version__ at import

# StatusCode mock
class _StatusCode:
    UNAVAILABLE = "UNAVAILABLE"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    INTERNAL = "INTERNAL"

_grpc_mock.StatusCode = _StatusCode
_grpc_mock.RpcError = type("RpcError", (Exception,), {"code": lambda self: None, "details": lambda self: ""})

# Force-inject grpc mock — always replace so rpc modules bind to our stub.
sys.modules["grpc"] = _grpc_mock

# Stub proto / context / grpc_health modules unconditionally (they're never
# real-imported in tests), but use setdefault for orchestrator.router so we
# don't clobber it when test_fallback_chain.py already holds a live reference.
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
    sys.modules[_mod] = MagicMock()
# dotenv is a real installed package — do NOT stub it here, or test_env_wizard.py
# (which calls `from dotenv import set_key` at test-run time) will get a MagicMock.
# orchestrator.router is NOT stubbed here — rpc.server imports it lazily inside
# handler functions (except the one re-export at line 47 which is harmless with
# the real module). Stubbing it would corrupt test_fallback_chain.py and
# test_adapters.py which hold live references to the real module.

# Force-reload rpc.server and rpc.client so they rebind grpc from the mock.
for _rpc_mod in ("rpc.server", "rpc.client"):
    sys.modules.pop(_rpc_mod, None)

# ── Import under test ─────────────────────────────────────────────────────────
from rpc.server import HealthServicer, get_health_servicer  # noqa: E402

# Zero retry delay so any accidental retry path does not sleep.
import rpc.client as _cli_mod  # noqa: E402
_cli_mod._RETRY_BASE_DELAY = 0.0

# Track which modules were injected so we can clean up after all tests run.
_GRPC_HEALTH_STUBS = [
    "grpc",
    "rpc.proto", "rpc.proto.cognirepo_pb2", "rpc.proto.cognirepo_pb2_grpc",
    "rpc.context_store",
    "grpc_health", "grpc_health.v1", "grpc_health.v1.health_pb2",
    "grpc_health.v1.health_pb2_grpc",
    # rpc.server only — rpc.client is left for test_grpc_multiagent.py to manage
    "rpc.server",
    # dotenv is NOT listed — it is a real installed package, never stubbed
]


@pytest.fixture(autouse=True, scope="module")
def _cleanup_grpc_stubs():
    """Evict grpc stubs after this module's tests finish."""
    yield
    for _mod in _GRPC_HEALTH_STUBS:
        sys.modules.pop(_mod, None)


# ── HealthServicer unit tests ─────────────────────────────────────────────────

class TestHealthServicer:

    def test_initial_status_serving(self):
        """All standard services start as SERVING."""
        svc = HealthServicer()
        assert svc.is_serving("") is True
        assert svc.is_serving("QueryService") is True
        assert svc.is_serving("ContextService") is True

    def test_unknown_service_returns_not_serving(self):
        """An unregistered service name returns NOT_SERVING."""
        svc = HealthServicer()
        assert svc.is_serving("NonExistentService") is False

    def test_set_status_not_serving(self):
        """set_status(serving=False) transitions to NOT_SERVING."""
        svc = HealthServicer()
        svc.set_status("QueryService", serving=False)
        assert svc.is_serving("QueryService") is False

    def test_set_status_restore_serving(self):
        """set_status(serving=True) restores SERVING after NOT_SERVING."""
        svc = HealthServicer()
        svc.set_status("QueryService", serving=False)
        svc.set_status("QueryService", serving=True)
        assert svc.is_serving("QueryService") is True

    def test_set_status_does_not_affect_other_services(self):
        """Changing one service status does not affect others."""
        svc = HealthServicer()
        svc.set_status("QueryService", serving=False)
        assert svc.is_serving("ContextService") is True
        assert svc.is_serving("") is True

    def test_add_to_server_noop_without_grpc_health(self):
        """add_to_server() is a no-op when grpc_health is unavailable."""
        svc = HealthServicer()
        mock_server = MagicMock()
        # Should not raise regardless of grpc_health availability
        svc.add_to_server(mock_server)

    def test_get_health_servicer_singleton(self):
        """get_health_servicer() returns the same instance across calls."""
        import rpc.server as srv
        srv._health_servicer = None  # reset singleton
        a = get_health_servicer()
        b = get_health_servicer()
        assert a is b

    def test_get_health_servicer_returns_health_servicer(self):
        """get_health_servicer() returns a HealthServicer instance."""
        import rpc.server as srv
        srv._health_servicer = None
        svc = get_health_servicer()
        assert isinstance(svc, HealthServicer)


# ── Client health() unit tests ────────────────────────────────────────────────

class TestClientHealth:

    def _make_client(self):
        """Build a CogniRepoClient with stubs pre-connected."""
        from rpc.client import CogniRepoClient
        client = CogniRepoClient.__new__(CogniRepoClient)
        client._host = "localhost"
        client._port = 50051
        client._address = "localhost:50051"
        client._channel = MagicMock()
        client._query_stub = MagicMock()
        client._ctx_stub = MagicMock()
        return client

    def test_health_falls_back_to_port_check_when_grpc_health_unavailable(self):
        """When grpc_health is not installed, health() falls back to port-open check."""
        import rpc.client as cli_mod
        original = cli_mod._GRPC_HEALTH_AVAILABLE
        cli_mod._GRPC_HEALTH_AVAILABLE = False

        client = self._make_client()
        with patch.object(client, "_is_port_open", return_value=True):
            assert client.health() is True

        cli_mod._GRPC_HEALTH_AVAILABLE = original

    def test_health_returns_false_when_port_closed(self):
        """Port-closed fallback returns False."""
        import rpc.client as cli_mod
        original = cli_mod._GRPC_HEALTH_AVAILABLE
        cli_mod._GRPC_HEALTH_AVAILABLE = False

        client = self._make_client()
        with patch.object(client, "_is_port_open", return_value=False):
            assert client.health() is False

        cli_mod._GRPC_HEALTH_AVAILABLE = original
