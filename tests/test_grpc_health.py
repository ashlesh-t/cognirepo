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

# StatusCode mock
class _StatusCode:
    UNAVAILABLE = "UNAVAILABLE"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    INTERNAL = "INTERNAL"

_grpc_mock.StatusCode = _StatusCode
_grpc_mock.RpcError = type("RpcError", (Exception,), {"code": lambda self: None, "details": lambda self: ""})
sys.modules.setdefault("grpc", _grpc_mock)

for _mod in (
    "rpc.proto",
    "rpc.proto.cognirepo_pb2",
    "rpc.proto.cognirepo_pb2_grpc",
    "rpc.context_store",
    "orchestrator.router",
    "dotenv",
):
    sys.modules.setdefault(_mod, MagicMock())

# ── Import under test ─────────────────────────────────────────────────────────
from rpc.server import HealthServicer, get_health_servicer  # noqa: E402


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
