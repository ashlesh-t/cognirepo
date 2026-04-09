# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Metrics middleware — records HTTP request counts and latency per route.

Uses the FastAPI route template (e.g. ``/memory/retrieve``) rather than the
raw URL, avoiding label cardinality blowup from path parameters.
"""
from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from api.metrics import REQUESTS_TOTAL, REQUEST_LATENCY, metrics_available

# Routes excluded from metric labelling (already exempted from other middleware)
_EXCLUDED = {"/metrics", "/health", "/ready"}


class MetricsMiddleware(BaseHTTPMiddleware):
    """Increment REQUESTS_TOTAL and record REQUEST_LATENCY on every response."""

    async def dispatch(self, request: Request, call_next):
        if not metrics_available() or request.url.path in _EXCLUDED:
            return await call_next(request)

        t0 = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - t0

        # Use the matched route template to avoid cardinality blowup
        route = request.url.path
        if request.scope.get("route"):
            route = getattr(request.scope["route"], "path", route)

        status = str(response.status_code)
        REQUESTS_TOTAL.labels(route=route, status=status).inc()
        REQUEST_LATENCY.labels(route=route).observe(elapsed)

        return response
