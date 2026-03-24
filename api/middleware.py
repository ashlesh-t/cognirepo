"""
JWT verification middleware — protects all routes except those in EXEMPT_PATHS.
"""
import os

import jwt
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

SECRET_KEY = os.environ.get("COGNIREPO_SECRET", "dev-secret-change-me")
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
            jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        except jwt.ExpiredSignatureError:
            return JSONResponse({"detail": "Token expired"}, status_code=401)
        except jwt.InvalidTokenError:
            return JSONResponse({"detail": "Invalid token"}, status_code=401)

        return await call_next(request)
