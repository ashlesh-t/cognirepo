# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
JWT verification middleware — protects all routes except those in EXEMPT_PATHS.

Secret is read lazily on each request so that environment variables set after
module import (e.g. in tests) are always picked up.
"""
import jwt
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

ALGORITHM = "HS256"
EXEMPT_PATHS = {"/login", "/docs", "/openapi.json", "/redoc"}


class JWTMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)

        token = auth_header[len("Bearer "):]
        try:
            from api.auth import get_jwt_secret  # pylint: disable=import-outside-toplevel
            jwt.decode(token, get_jwt_secret(), algorithms=[ALGORITHM])
        except jwt.ExpiredSignatureError:
            return JSONResponse({"detail": "Token expired"}, status_code=401)
        except jwt.InvalidTokenError:
            return JSONResponse({"detail": "Invalid token"}, status_code=401)
        except RuntimeError:
            return JSONResponse({"detail": "JWT secret not configured"}, status_code=500)

        return await call_next(request)
