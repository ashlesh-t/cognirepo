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
import os
import threading
import time
from concurrent import futures

import grpc

from rpc.context_store import get_store
from rpc.proto import cognirepo_pb2 as pb2
from rpc.proto import cognirepo_pb2_grpc as pb2_grpc

try:
    from grpc_health.v1 import health as grpc_health_mod
    from grpc_health.v1 import health_pb2, health_pb2_grpc
    _GRPC_HEALTH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _GRPC_HEALTH_AVAILABLE = False

try:
    from orchestrator.router import stream_route  # noqa: F401  (re-exported for patching in tests)
except ImportError:  # orchestrator not yet available in lightweight test envs
    stream_route = None  # type: ignore[assignment]

DEFAULT_PORT = 50051
_MAX_WORKERS = 10

# Inactivity management
_last_activity = time.time()
_activity_lock = threading.Lock()


def _update_activity():
    global _last_activity
    with _activity_lock:
        _last_activity = time.time()


def _check_inactivity(server: grpc.Server, timeout: int):
    """Background thread that stops the server after 'timeout' seconds of silence."""
    if timeout <= 0:
        return
    while True:
        time.sleep(30)
        with _activity_lock:
            elapsed = time.time() - _last_activity
        if elapsed > timeout:
            print(f"[gRPC] Inactive for {timeout}s. Shutting down automatically.")
            # We use os._exit(0) for a hard exit of the daemon process
            # because server.stop() doesn't always break the block loop cleanly.
            server.stop(grace=2)
            os._exit(0)


# ── QueryService implementation ───────────────────────────────────────────────

class QueryServiceServicer(pb2_grpc.QueryServiceServicer):
    """Delegates sub-queries to the model router."""

    def SubQuery(
        self,
        request: pb2.QueryRequest,
        context: grpc.ServicerContext,
    ) -> pb2.QueryResponse:
        _update_activity()
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
        True streaming via orchestrator.router.stream_route().

        Each text chunk emitted by the model adapter is forwarded immediately
        as a QueryResponse, so the first gRPC chunk arrives before the full
        response is generated.  Handles client disconnection (context.is_active)
        and falls back to the blocking SubQuery path if the streaming generator
        raises on the first chunk.
        """
        _update_activity()
        try:
            # stream_route is imported at module level; local reference kept for clarity
            _stream_fn = stream_route  # noqa: F821
            clf_info: dict = {}
            chunks_sent = 0

            gen = _stream_fn(
                query=request.query,
                max_tokens=request.max_tokens or 1024,
            )

            for chunk in gen:
                if not context.is_active():
                    gen.close()
                    return
                chunks_sent += 1
                yield pb2.QueryResponse(
                    result=chunk,
                    confidence=clf_info.get("confidence", 0.0),
                    model_used=clf_info.get("model", ""),
                    provider_used=clf_info.get("provider", ""),
                    tokens_used=0,
                    error=False,
                    error_message="",
                )

            if chunks_sent == 0:
                # Stream produced nothing — fall back to blocking call
                yield from [self.SubQuery(request, context)]

        except Exception as exc:  # pylint: disable=broad-except
            # Streaming failed — yield a single error response (never crash server)
            yield pb2.QueryResponse(
                result="",
                error=True,
                error_message=str(exc),
            )


# ── ContextService implementation ─────────────────────────────────────────────

class ContextServiceServicer(pb2_grpc.ContextServiceServicer):
    """Shared session context store over gRPC."""

    def PushContext(
        self,
        request: pb2.ContextSyncRequest,
        context: grpc.ServicerContext,
    ) -> pb2.ContextSyncResponse:
        _update_activity()
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
        _update_activity()
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
        _update_activity()
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
    return {"STANDARD": 0.7, "COMPLEX": 0.8, "EXPERT": 0.9}.get(tier, 0.5)


# ── HealthServicer ────────────────────────────────────────────────────────────

class HealthServicer:
    """
    Standard gRPC health servicer.

    Uses ``grpc_health.v1`` if available, otherwise provides a minimal
    compatible implementation that returns SERVING for all services.

    The canonical service names are:
        ""                      — overall server health
        "QueryService"          — sub-query delegation
        "ContextService"        — shared context store
    """

    SERVING = 1
    NOT_SERVING = 2

    def __init__(self):
        self._status: dict[str, int] = {
            "": self.SERVING,
            "QueryService": self.SERVING,
            "ContextService": self.SERVING,
        }
        # If the package is available, delegate to it for full Watch support
        self._delegate = None
        if _GRPC_HEALTH_AVAILABLE:
            self._delegate = grpc_health_mod.HealthServicer()
            for svc in self._status:
                self._delegate.set(svc, health_pb2.HealthCheckResponse.SERVING)

    def set_status(self, service: str, serving: bool) -> None:
        """Update the serving status for a named service."""
        status = self.SERVING if serving else self.NOT_SERVING
        self._status[service] = status
        if self._delegate is not None:
            proto_status = (
                health_pb2.HealthCheckResponse.SERVING if serving
                else health_pb2.HealthCheckResponse.NOT_SERVING
            )
            self._delegate.set(service, proto_status)

    def is_serving(self, service: str = "") -> bool:
        """Return True if the service is currently SERVING."""
        return self._status.get(service, self.NOT_SERVING) == self.SERVING

    def add_to_server(self, server: grpc.Server) -> None:
        """Register this servicer on the gRPC server."""
        if _GRPC_HEALTH_AVAILABLE and self._delegate is not None:
            health_pb2_grpc.add_HealthServicer_to_server(self._delegate, server)


# Module-level singleton so tests and server lifecycle code can share it
_health_servicer: HealthServicer | None = None


def get_health_servicer() -> HealthServicer:
    """Return the module-level HealthServicer (created lazily)."""
    global _health_servicer  # pylint: disable=global-statement
    if _health_servicer is None:
        _health_servicer = HealthServicer()
    return _health_servicer


# ── server lifecycle ──────────────────────────────────────────────────────────

def start_server(
    port: int = DEFAULT_PORT,
    block: bool = True,
    idle_timeout: int = 0,
) -> grpc.Server:
    """
    Create, register services, and start the gRPC server.

    Parameters
    ----------
    port         : TCP port to listen on
    block        : if True, blocks until KeyboardInterrupt (CLI mode);
                   if False, returns the server object for programmatic control.
    idle_timeout : shutdown after this many seconds of inactivity (0 to disable).
    """
    from dotenv import load_dotenv  # pylint: disable=import-outside-toplevel
    load_dotenv()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS))
    pb2_grpc.add_QueryServiceServicer_to_server(QueryServiceServicer(), server)
    pb2_grpc.add_ContextServiceServicer_to_server(ContextServiceServicer(), server)
    health_svc = get_health_servicer()
    health_svc.add_to_server(server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    print(f"[gRPC] CogniRepo server listening on port {port}", flush=True)

    if idle_timeout > 0:
        print(f"[gRPC] Idle timeout set to {idle_timeout}s")
        t = threading.Thread(
            target=_check_inactivity,
            args=(server, idle_timeout),
            daemon=True,
        )
        t.start()

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
    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=0,
        help="Shut down after N seconds of inactivity (0 to disable)",
    )
    args = parser.parse_args()
    start_server(port=args.port, block=True, idle_timeout=args.idle_timeout)
