# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Rate-limit middleware — wraps every non-exempt route with a token-bucket check.

Client identity comes from the JWT ``sub`` claim if a valid Bearer token is
present, otherwise falls back to the client IP.
"""
from __future__ import annotations

import logging
import math

import jwt
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from api.rate_limit import get_limiter
from api.metrics import RATE_LIMIT_DENIED

logger = logging.getLogger(__name__)

# Routes excluded from rate limiting
_EXEMPT = {"/health", "/ready", "/login", "/metrics", "/docs", "/openapi.json", "/redoc"}

_JWT_ALGORITHM = "HS256"


def _extract_client_id(request: Request) -> str:
    """
    Try to extract a stable client ID from the JWT sub claim.
    Falls back to the remote client IP.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[len("Bearer "):]
        try:
            from api.auth import get_jwt_secret  # pylint: disable=import-outside-toplevel
            payload = jwt.decode(token, get_jwt_secret(), algorithms=[_JWT_ALGORITHM])
            sub = payload.get("sub")
            if sub:
                return str(sub)
        except Exception:  # pylint: disable=broad-except
            pass
    # Fall back to remote IP
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = request.client
    return client.host if client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforce per-client request rate limits."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path in _EXEMPT:
            return await call_next(request)

        client_id = _extract_client_id(request)
        limiter = get_limiter()
        allowed, retry_after = await limiter.check(client_id)

        if not allowed:
            RATE_LIMIT_DENIED.labels(client_id=client_id).inc()
            retry_int = math.ceil(retry_after)
            logger.warning(
                "rate_limit.denied",
                extra={"client_id": client_id, "retry_after": retry_int},
            )
            return JSONResponse(
                {"detail": "Rate limit exceeded", "retry_after_seconds": retry_int},
                status_code=429,
                headers={"Retry-After": str(retry_int)},
            )

        return await call_next(request)
