# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""FastAPI app for the local control API (``/api/v1``). Every request passes the guard below."""
from __future__ import annotations

import os
import time
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from interface.ui import security as sec
from interface.ui.audit import AuditLog
from interface.ui.status import API_VERSION, collect_status

_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


class SessionBody(BaseModel):
    token: str


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def create_app(cfg: sec.SecurityConfig, repo_root: str, audit: AuditLog | None = None) -> FastAPI:
    """Build the app. ``cfg`` fixes the token/port; ``repo_root`` is the repo this UI serves."""
    app = FastAPI(
        title="CogniRepo control API",
        version=API_VERSION,
        description="Local-only control API. Loopback bind, per-session token, Host/Origin allowlists.",
        docs_url=None, redoc_url=None, openapi_url="/api/v1/openapi.json",
    )
    app.state.cfg = cfg
    app.state.repo_root = os.path.abspath(repo_root)
    app.state.audit = audit
    app.state.started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    def _deny(status: int, error: str, **headers: str) -> JSONResponse:
        return JSONResponse({"error": error}, status_code=status, headers=headers)

    @app.middleware("http")
    async def guard(request: Request, call_next):  # noqa: ANN001
        if not cfg.host_ok(request.headers.get("host")):
            return _deny(403, "bad_host")
        if not cfg.origin_ok(request.headers.get("origin")):
            return _deny(403, "bad_origin")
        path = request.url.path
        if path.startswith("/api/"):
            client = _client(request)
            retry = cfg.limiter.retry_after(client)
            if retry > 0:
                return _deny(429, "locked_out", **{"Retry-After": str(int(retry) + 1)})
            if path != "/api/v1/session":  # /session validates the token in its body
                supplied = sec.extract_token(request.headers, request.cookies)
                if not sec.tokens_equal(supplied, cfg.token):
                    if supplied:  # a missing token is not an attack; a wrong one is
                        cfg.limiter.record_failure(client)
                    return _deny(401, "unauthorized")
                cfg.limiter.record_success(client)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/v1/session")
    async def session(body: SessionBody, request: Request) -> JSONResponse:
        """Swap the one-time URL-fragment token for an httpOnly SameSite=Strict cookie."""
        client = _client(request)
        if not sec.tokens_equal(body.token, cfg.token):
            cfg.limiter.record_failure(client)
            if audit:
                audit.log("session_denied", client=client)
            return _deny(401, "unauthorized")
        cfg.limiter.record_success(client)
        resp = JSONResponse({"ok": True})
        resp.set_cookie(sec.COOKIE_NAME, cfg.token, httponly=True, samesite="strict", path="/")
        if audit:
            audit.log("session_created", client=client)
        return resp

    @app.get("/api/v1/status")
    async def status(request: Request) -> dict[str, Any]:
        return collect_status(app.state.repo_root, app.state.started_at, os.getpid())

    @app.get("/api/v1/graph")
    def graph(  # sync on purpose: runs in the threadpool, not the event loop
        node: str | None = Query(default=None, max_length=512),
        depth: int = Query(default=1, ge=0, le=3),
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> dict[str, Any]:
        """Read-only, bounded knowledge-graph slice (never the whole graph)."""
        from interface.tools.graph_view import graph_view  # pylint: disable=import-outside-toplevel
        return graph_view(node=node, depth=depth, limit=limit)

    return app
