# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
CogniRepo gRPC client — used internally by model adapters when they need
to delegate a sub-query to another model tier.

Typical usage (inside anthropic_adapter.py or router.py):

    from rpc.client import CogniRepoClient

    with CogniRepoClient() as client:
        result = client.sub_query(
            query="what does verify_token return on expiry?",
            context_id="q_abc123",
            source_model="claude-sonnet-4-6",
            target_tier="STANDARD",
        )
        print(result.result, result.confidence)

        # Push intermediate reasoning into shared context
        client.push_context("q_abc123", "reasoning_step_1", "JWT uses HS256...")

        # Pull it back (e.g. after Gemini finishes a sub-lookup)
        entries = client.get_context("q_abc123")
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import time
import uuid

import grpc

from rpc.proto import cognirepo_pb2 as pb2
from rpc.proto import cognirepo_pb2_grpc as pb2_grpc

try:
    from grpc_health.v1 import health_pb2, health_pb2_grpc as health_grpc
    _GRPC_HEALTH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _GRPC_HEALTH_AVAILABLE = False

logger = logging.getLogger(__name__)

_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 0.5  # seconds; doubles on each attempt

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 50051
DEFAULT_IDLE_TIMEOUT = 900  # 15 minutes


class CogniRepoClient:
    """
    Thin wrapper around the two gRPC stubs (QueryStub + ContextStub).

    Use as a context manager to ensure channel cleanup:
        with CogniRepoClient() as c:
            ...

    Or manage manually:
        c = CogniRepoClient(); c.connect()
        ...
        c.close()
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self._host = host
        self._port = port
        self._address = f"{host}:{port}"
        self._channel: grpc.Channel | None = None
        self._query_stub: pb2_grpc.QueryServiceStub | None = None
        self._ctx_stub: pb2_grpc.ContextServiceStub | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> "CogniRepoClient":
        """Initialize the gRPC channel and stubs."""
        if self._host in ("localhost", "127.0.0.1"):
            self._ensure_server_running()

        self._channel = grpc.insecure_channel(self._address)
        self._query_stub = pb2_grpc.QueryServiceStub(self._channel)
        self._ctx_stub = pb2_grpc.ContextServiceStub(self._channel)
        return self

    def _ensure_server_running(self) -> None:
        """Check if port is open; if not, spawn the server in the background."""
        if self._is_port_open():
            return

        print(f"[gRPC] Server not found on port {self._port}. Starting on-demand...")
        try:
            # Start server with 15-min idle timeout
            subprocess.Popen(  # pylint: disable=consider-using-with  # nosec B603
                ["cognirepo", "serve-grpc", "--port", str(self._port),
                 "--idle-timeout", str(DEFAULT_IDLE_TIMEOUT)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,  # ensure it survives client exit
            )
            # Wait up to 5s for the server to bind the port
            for _ in range(25):
                time.sleep(0.2)
                if self._is_port_open():
                    print(f"[gRPC] Server started on port {self._port}.")
                    return
            print("[gRPC] Warning: server start timed out. Connection may fail.")
        except Exception as exc:  # pylint: disable=broad-except
            print(f"[gRPC] Failed to auto-start server: {exc}")

    def _is_port_open(self) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            return s.connect_ex((self._host, self._port)) == 0

    def close(self) -> None:
        """Close the underlying gRPC channel."""
        if self._channel:
            self._channel.close()
            self._channel = None

    def __enter__(self) -> "CogniRepoClient":
        return self.connect()

    def __exit__(self, *_) -> None:
        self.close()

    # ── QueryService ──────────────────────────────────────────────────────────

    def health(self, service: str = "", timeout: float = 5.0) -> bool:
        """
        Check the server health via the gRPC Health proto.

        Returns True if the server reports SERVING, False otherwise
        (including when ``grpcio-health-checking`` is not installed).
        """
        if not _GRPC_HEALTH_AVAILABLE:
            # Fall back to a simple port-open check
            return self._is_port_open()
        self._ensure_connected()
        try:
            stub = health_grpc.HealthStub(self._channel)
            req = health_pb2.HealthCheckRequest(service=service)
            resp = stub.Check(req, timeout=timeout)
            return resp.status == health_pb2.HealthCheckResponse.SERVING
        except grpc.RpcError as exc:
            logger.warning("health check failed: %s — %s", exc.code(), exc.details())
            return False

    def sub_query(
        self,
        query: str,
        context_id: str = "",
        source_model: str = "",
        target_tier: str = "STANDARD",
        max_tokens: int = 512,
        metadata: dict[str, str] | None = None,
        timeout: float = 30.0,
        trace_id: str | None = None,
    ) -> pb2.QueryResponse:
        """
        Delegate a sub-query to the gRPC server (which routes it through the
        model router).  Returns a QueryResponse proto.

        Retries up to ``_RETRY_ATTEMPTS`` times with exponential backoff on
        transient gRPC errors (UNAVAILABLE, DEADLINE_EXCEEDED).  The
        ``trace_id`` is propagated through gRPC metadata for log correlation.

        Parameters
        ----------
        query        : the sub-question to answer
        context_id   : session ID so the result is stored in shared context
        source_model : calling model — informational, stored in session metadata
        target_tier  : hint for routing ("STANDARD" for lightweight lookups)
        max_tokens   : response length cap
        timeout      : per-attempt deadline in seconds
        trace_id     : optional correlation ID (generated if not provided)
        """
        self._ensure_connected()
        _trace_id = trace_id or str(uuid.uuid4())
        _meta = [("x-trace-id", _trace_id)]

        request = pb2.QueryRequest(
            query=query,
            context_id=context_id,
            source_model=source_model,
            target_tier=target_tier,
            max_tokens=max_tokens,
            metadata={**(metadata or {}), "trace_id": _trace_id},
        )

        last_exc: grpc.RpcError | None = None
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                return self._query_stub.SubQuery(request, timeout=timeout, metadata=_meta)
            except grpc.RpcError as exc:
                code = exc.code()
                if code not in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
                    raise
                last_exc = exc
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "sub_query attempt %d/%d failed (trace_id=%s): %s — %s; retrying in %.1fs",
                    attempt + 1, _RETRY_ATTEMPTS, _trace_id, code, exc.details(), delay,
                )
                time.sleep(delay)

        raise last_exc  # type: ignore[misc]

    def sub_query_stream(
        self,
        query: str,
        context_id: str = "",
        source_model: str = "",
        target_tier: str = "FAST",
        max_tokens: int = 512,
        timeout: float = 60.0,
    ):
        """Generator that yields QueryResponse chunks as they arrive."""
        self._ensure_connected()
        request = pb2.QueryRequest(
            query=query,
            context_id=context_id,
            source_model=source_model,
            target_tier=target_tier,
            max_tokens=max_tokens,
        )
        yield from self._query_stub.SubQueryStream(request, timeout=timeout)

    # ── ContextService ────────────────────────────────────────────────────────

    def push_context(
        self,
        context_id: str,
        key: str,
        value: str,
        author: str = "",
        timeout: float = 5.0,
    ) -> pb2.ContextSyncResponse:
        """Push a key-value pair into the shared session context."""
        import time  # pylint: disable=import-outside-toplevel
        self._ensure_connected()
        request = pb2.ContextSyncRequest(
            context_id=context_id,
            author=author,
            key=key,
            value=value,
            timestamp=int(time.time() * 1000),
        )
        return self._ctx_stub.PushContext(request, timeout=timeout)

    def get_context(
        self,
        context_id: str,
        key: str = "",
        timeout: float = 5.0,
    ) -> dict[str, str]:
        """Pull session context entries.  Empty key returns all."""
        self._ensure_connected()
        request = pb2.ContextGetRequest(context_id=context_id, key=key)
        response = self._ctx_stub.GetContext(request, timeout=timeout)
        return dict(response.entries)

    def list_sessions(self, limit: int = 20, timeout: float = 5.0) -> list[str]:
        """Return active session IDs sorted by most-recently-updated."""
        self._ensure_connected()
        request = pb2.ListSessionsRequest(limit=limit)
        response = self._ctx_stub.ListSessions(request, timeout=timeout)
        return list(response.context_ids)

    # ── internal ──────────────────────────────────────────────────────────────

    def _ensure_connected(self) -> None:
        if self._channel is None:
            self.connect()


# ── module-level convenience ──────────────────────────────────────────────────

def sub_query(
    query: str,
    context_id: str = "",
    source_model: str = "",
    target_tier: str = "STANDARD",
    max_tokens: int = 512,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> str:
    """
    One-shot sub-query helper — opens a channel, fires the query, closes.
    Returns the result text string (or empty string on error).

    Use the CogniRepoClient class directly for batched calls to avoid
    the per-call channel overhead.
    """
    try:
        with CogniRepoClient(host=host, port=port) as client:
            resp = client.sub_query(
                query=query,
                context_id=context_id,
                source_model=source_model,
                target_tier=target_tier,
                max_tokens=max_tokens,
            )
            return resp.result
    except grpc.RpcError as exc:
        return f"[gRPC error: {exc.code()} — {exc.details()}]"
