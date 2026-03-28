# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
CogniRepo gRPC server — runs on a separate port from FastAPI (default 50051).

Services
--------
QueryService   — SubQuery / SubQueryStream (inter-model delegation)
ContextService — PushContext / GetContext / ListSessions

Start standalone:
    python -m rpc.server              # default port 50051
    python -m rpc.server --port 50052

Or call from code:
    from rpc.server import start_server, stop_server
    server = start_server(port=50051, block=False)
    ...
    stop_server(server)
"""
from __future__ import annotations

import argparse
import time
from concurrent import futures

import grpc

from rpc.context_store import get_store
from rpc.proto import cognirepo_pb2 as pb2
from rpc.proto import cognirepo_pb2_grpc as pb2_grpc

DEFAULT_PORT = 50051
_MAX_WORKERS = 10


# ── QueryService implementation ───────────────────────────────────────────────

class QueryServiceServicer(pb2_grpc.QueryServiceServicer):
    """Delegates sub-queries to the model router."""

    def SubQuery(
        self,
        request: pb2.QueryRequest,
        context: grpc.ServicerContext,
    ) -> pb2.QueryResponse:
        try:
            from orchestrator.router import route  # pylint: disable=import-outside-toplevel
            result = route(
                query=request.query,
                top_k=5,
                max_tokens=request.max_tokens or 1024,
            )
            # Store result in shared context if context_id provided
            if request.context_id:
                store = get_store()
                store.push(
                    request.context_id,
                    key=f"subquery_result_{int(time.time()*1000)}",
                    value=result.response.text,
                )
            return pb2.QueryResponse(
                result=result.response.text,
                confidence=_confidence_from_tier(result.classifier.tier),
                model_used=result.response.model,
                provider_used=result.response.provider,
                tokens_used=result.response.usage.get("output_tokens", 0),
                error=bool(result.error),
                error_message=result.error,
            )
        except Exception as exc:  # pylint: disable=broad-except
            return pb2.QueryResponse(
                result="",
                error=True,
                error_message=str(exc),
            )

    def SubQueryStream(
        self,
        request: pb2.QueryRequest,
        context: grpc.ServicerContext,
    ):
        """
        Streaming version — yields a single QueryResponse today (the router
        doesn't stream yet).  Yields partial tokens once streaming is added
        to model adapters.
        """
        response = self.SubQuery(request, context)
        # Split by sentence for a realistic streaming feel when adapters upgrade.
        import re  # pylint: disable=import-outside-toplevel
        sentences = re.split(r"(?<=[.!?])\s+", response.result or "")
        if not sentences:
            yield response
            return
        for i, sentence in enumerate(sentences):
            yield pb2.QueryResponse(
                result=sentence + (" " if i < len(sentences) - 1 else ""),
                confidence=response.confidence,
                model_used=response.model_used,
                provider_used=response.provider_used,
                tokens_used=0,
                error=response.error,
                error_message=response.error_message,
            )


# ── ContextService implementation ─────────────────────────────────────────────

class ContextServiceServicer(pb2_grpc.ContextServiceServicer):
    """Shared session context store over gRPC."""

    def PushContext(
        self,
        request: pb2.ContextSyncRequest,
        context: grpc.ServicerContext,
    ) -> pb2.ContextSyncResponse:
        try:
            store = get_store()
            version = store.push(request.context_id, request.key, request.value)
            return pb2.ContextSyncResponse(ok=True, version=version)
        except Exception as exc:  # pylint: disable=broad-except
            context.set_details(str(exc))
            context.set_code(grpc.StatusCode.INTERNAL)
            return pb2.ContextSyncResponse(ok=False)

    def GetContext(
        self,
        request: pb2.ContextGetRequest,
        context: grpc.ServicerContext,
    ) -> pb2.ContextGetResponse:
        try:
            store = get_store()
            entries = store.get(request.context_id, request.key)
            last_updated = store.last_updated(request.context_id)
            return pb2.ContextGetResponse(
                context_id=request.context_id,
                entries=entries,
                last_updated=last_updated,
            )
        except Exception as exc:  # pylint: disable=broad-except
            context.set_details(str(exc))
            context.set_code(grpc.StatusCode.INTERNAL)
            return pb2.ContextGetResponse(context_id=request.context_id)

    def ListSessions(
        self,
        request: pb2.ListSessionsRequest,
        context: grpc.ServicerContext,
    ) -> pb2.ListSessionsResponse:
        try:
            store = get_store()
            ids = store.list_sessions(limit=request.limit)
            return pb2.ListSessionsResponse(context_ids=ids)
        except Exception as exc:  # pylint: disable=broad-except
            context.set_details(str(exc))
            context.set_code(grpc.StatusCode.INTERNAL)
            return pb2.ListSessionsResponse()


# ── helpers ───────────────────────────────────────────────────────────────────

def _confidence_from_tier(tier: str) -> float:
    """Map classifier tier to a rough confidence value."""
    return {"FAST": 0.7, "BALANCED": 0.8, "DEEP": 0.9}.get(tier, 0.5)


# ── server lifecycle ──────────────────────────────────────────────────────────

def start_server(port: int = DEFAULT_PORT, block: bool = True) -> grpc.Server:
    """
    Create, register services, and start the gRPC server.

    Parameters
    ----------
    port  : TCP port to listen on
    block : if True, blocks until KeyboardInterrupt (CLI mode);
            if False, returns the server object for programmatic control.
    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS))
    pb2_grpc.add_QueryServiceServicer_to_server(QueryServiceServicer(), server)
    pb2_grpc.add_ContextServiceServicer_to_server(ContextServiceServicer(), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    print(f"[gRPC] CogniRepo server listening on port {port}", flush=True)

    if block:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            print("[gRPC] Shutting down...")
            server.stop(grace=5)

    return server


def stop_server(server: grpc.Server, grace: float = 5.0) -> None:
    """Stop the gRPC server with a grace period."""
    server.stop(grace=grace)


# ── __main__ ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CogniRepo gRPC server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    start_server(port=args.port, block=True)
