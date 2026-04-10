# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
CogniRepo FastAPI application.

Run with:
    uvicorn api.main:app --reload

All routes except /login require a Bearer JWT obtained from POST /login.
"""
from dotenv import load_dotenv
load_dotenv()

from config.logging import setup_logging
setup_logging()

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response

from api.auth import router as auth_router
from api.metrics import metrics_available, get_metrics_output
from api.middleware import JWTMiddleware
from api.middleware_metrics import MetricsMiddleware
from api.middleware_ratelimit import RateLimitMiddleware
from api.middleware_tracing import TracingMiddleware
from api.routes.episodic import router as episodic_router
from api.routes.graph import router as graph_router
from api.routes.memory import router as memory_router
from api.routes.status import router as status_router

app = FastAPI(
    title="CogniRepo API",
    description=(
        "REST adapter over the CogniRepo tools layer "
        "(FAISS semantic memory + episodic log + docs search)."
    ),
    version="0.1.0",
)

# Middleware stack (applied inside-out — last added = first to run):
#   TracingMiddleware → MetricsMiddleware → RateLimitMiddleware → JWTMiddleware
app.add_middleware(JWTMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(MetricsMiddleware)
app.add_middleware(TracingMiddleware)

app.include_router(auth_router)
app.include_router(memory_router)
app.include_router(episodic_router)
app.include_router(graph_router)
app.include_router(status_router)


@app.get("/metrics", include_in_schema=False)
async def metrics_endpoint():
    """Prometheus metrics — no auth required."""
    if not metrics_available():
        return JSONResponse(
            {"detail": "prometheus_client not installed. Run: pip install cognirepo[dev]"},
            status_code=501,
        )
    body, content_type = get_metrics_output()
    return Response(content=body, media_type=content_type)


@app.get("/health")
async def health() -> JSONResponse:
    """Health check endpoint — used by Docker HEALTHCHECK and load balancers."""
    from memory.circuit_breaker import get_breaker  # pylint: disable=import-outside-toplevel
    breaker = get_breaker()
    return JSONResponse({
        "status": "ok",
        "ready": True,
        "circuit_breaker": breaker.state.value,
    })


@app.get("/ready")
async def ready() -> JSONResponse:
    """
    Lightweight readiness probe — returns immediately when the server process
    is accepting connections.  Poll this before issuing /login to avoid the
    JSONDecodeError that occurs when curl fires before uvicorn is fully bound.

    Example (bash):
        until curl -sf http://localhost:8000/ready; do sleep 0.2; done
        TOKEN=$(curl -s -X POST http://localhost:8000/login \\
                  -H 'Content-Type: application/json' \\
                  -d '{"password":"changeme"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
    """
    return JSONResponse({"status": "ready"})
