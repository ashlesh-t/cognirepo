# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Tracing middleware — generates/propagates X-Trace-Id on every request
and sets the cogni_trace_id ContextVar so all log lines in the same
request carry the same trace ID.
"""
from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from config.logging import cogni_trace_id, new_trace_id

logger = logging.getLogger(__name__)


class TracingMiddleware(BaseHTTPMiddleware):
    """Inject and propagate X-Trace-Id for every incoming request."""

    async def dispatch(self, request: Request, call_next):
        # Honour an incoming trace ID (e.g. from an upstream caller)
        incoming = request.headers.get("X-Trace-Id")
        if incoming:
            cogni_trace_id.set(incoming)
            tid = incoming
        else:
            tid = new_trace_id()

        t0 = time.perf_counter()
        logger.info(
            "request.start",
            extra={"method": request.method, "path": request.url.path},
        )

        response = await call_next(request)

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        logger.info(
            "request.end",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "elapsed_ms": elapsed_ms,
            },
        )

        response.headers["X-Trace-Id"] = tid
        return response
