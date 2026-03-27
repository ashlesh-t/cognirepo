# SPDX-FileCopyrightText: 2026 Ashlesh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/your-username/cognirepo
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
            target_tier="FAST",
        )
        print(result.result, result.confidence)

        # Push intermediate reasoning into shared context
        client.push_context("q_abc123", "reasoning_step_1", "JWT uses HS256...")

        # Pull it back (e.g. after Gemini finishes a sub-lookup)
        entries = client.get_context("q_abc123")
"""
from __future__ import annotations

import grpc

from rpc.proto import cognirepo_pb2 as pb2
from rpc.proto import cognirepo_pb2_grpc as pb2_grpc

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 50051


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
        self._address = f"{host}:{port}"
        self._channel: grpc.Channel | None = None
        self._query_stub: pb2_grpc.QueryServiceStub | None = None
        self._ctx_stub: pb2_grpc.ContextServiceStub | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> "CogniRepoClient":
        self._channel = grpc.insecure_channel(self._address)
        self._query_stub = pb2_grpc.QueryServiceStub(self._channel)
        self._ctx_stub = pb2_grpc.ContextServiceStub(self._channel)
        return self

    def close(self) -> None:
        if self._channel:
            self._channel.close()
            self._channel = None

    def __enter__(self) -> "CogniRepoClient":
        return self.connect()

    def __exit__(self, *_) -> None:
        self.close()

    # ── QueryService ──────────────────────────────────────────────────────────

    def sub_query(
        self,
        query: str,
        context_id: str = "",
        source_model: str = "",
        target_tier: str = "FAST",
        max_tokens: int = 512,
        metadata: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> pb2.QueryResponse:
        """
        Delegate a sub-query to the gRPC server (which routes it through the
        model router).  Returns a QueryResponse proto.

        Parameters
        ----------
        query        : the sub-question to answer
        context_id   : session ID so the result is stored in shared context
        source_model : calling model — informational, stored in session metadata
        target_tier  : hint for routing ("FAST" for Gemini Flash lookups)
        max_tokens   : response length cap
        timeout      : seconds before the call is cancelled
        """
        self._ensure_connected()
        request = pb2.QueryRequest(
            query=query,
            context_id=context_id,
            source_model=source_model,
            target_tier=target_tier,
            max_tokens=max_tokens,
            metadata=metadata or {},
        )
        return self._query_stub.SubQuery(request, timeout=timeout)

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
    target_tier: str = "FAST",
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
