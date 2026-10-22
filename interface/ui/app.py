# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""FastAPI app for the local control API (``/api/v1``). Every request passes the guard below."""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from fastapi import Body, FastAPI, Header, Path, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StrictBool

from core import events
from interface.ui import security as sec
from interface.ui import event_stream
from interface.ui import repo_select
from interface.ui import models as m
from interface.ui.audit import AuditLog
from interface.ui.services import ServiceError, ServiceManager
from interface.ui.status import API_VERSION, _store_dir, collect_status

_BOOTSTRAP_JS = """\
// Swap the one-time URL-fragment token for an httpOnly SameSite=Strict cookie, then strip the URL.
(async () => {
  const m = /(?:^#|&)token=([^&]+)/.exec(location.hash);
  const out = document.getElementById('out');
  const say = (t) => { if (out) out.textContent = t; };
  if (m) {
    const token = decodeURIComponent(m[1]);
    history.replaceState(null, '', location.pathname + location.search);  // strip FIRST
    const r = await fetch('/api/v1/session', {method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({token})});
    if (!r.ok) { say('Session rejected (' + r.status + '). Re-run: cognirepo ui'); return; }
  }
  const s = await fetch('/api/v1/status', {credentials: 'same-origin'});
  say(s.ok ? JSON.stringify(await s.json(), null, 2) : 'Not signed in. Run: cognirepo ui');
})();
"""

_FALLBACK_PAGE = """<!doctype html><meta charset="utf-8"><title>CogniRepo</title>
<body style="background:#080808;color:#e8e8e8;font:14px ui-monospace,monospace;padding:2rem">
<h1>cognirepo</h1>
<p>The Engram console package is not installed. Install it with <code>pip install cognirepo-console</code>.</p>
<p>The local API is running; status below.</p><pre id="out">loading…</pre>
<script src="/_cognirepo/bootstrap.js"></script>"""

_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


class SessionBody(BaseModel):
    token: str


class ConfirmBody(BaseModel):
    confirm: StrictBool = False  # strict: "true" or 1 must not count as an explicit confirm
    dry_run: StrictBool = False  # `prune` only: report what would be pruned, change nothing


class AutoIndexRequest(ConfirmBody):
    enabled: StrictBool


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def create_app(cfg: sec.SecurityConfig, repo_root: str, audit: AuditLog | None = None,
               services: ServiceManager | None = None, console_dir: str | None = None) -> FastAPI:
    """Build the app. ``cfg`` fixes the token/port; ``repo_root`` is the repo this UI serves."""
    app = FastAPI(
        title="CogniRepo control API",
        version=f"{API_VERSION}.0.0",
        description="Local-only control API. Loopback bind, per-session token, Host/Origin allowlists.",
        docs_url=None, redoc_url=None, openapi_url="/api/v1/openapi.json",
    )
    app.state.cfg = cfg
    app.state.repo_root = os.path.abspath(repo_root)
    app.state.audit = audit
    svc = services or ServiceManager(app.state.repo_root)
    app.state.services = svc
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
        # A handler may set a stricter/different policy (the sandboxed insights report); default otherwise.
        response.headers.setdefault("Content-Security-Policy", _CSP)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    def _sel(repo: str | None) -> tuple[str, str, bool]:
        """(root, store, is_served) for ``?repo=``; raises RepoSelectError."""
        root, store = repo_select.select(repo, app.state.repo_root)
        return root, store, root == os.path.abspath(app.state.repo_root)

    @app.exception_handler(repo_select.RepoSelectError)
    async def _repo_error(_request: Request, exc: repo_select.RepoSelectError) -> JSONResponse:
        return _deny(exc.status, exc.code)

    def _served_or_deny(repo: str | None, request: Request, what: str) -> JSONResponse | None:
        """Writes and live service state exist only for the served repo; audited like any other denial."""
        try:
            repo_select.require_served(repo, app.state.repo_root)
        except repo_select.RepoSelectError as exc:
            if audit:
                audit.log(f"{what}_denied_repo", repo=str(repo)[:200], result=exc.code, client=_client(request),
                          origin=request.headers.get("origin"))
            return _deny(exc.status, exc.code)
        return None

    @app.post("/api/v1/session", response_model=m.OkBody, responses={401: {"model": m.ErrorBody}, 429: {"model": m.ErrorBody}})
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

    @app.get("/api/v1/status", response_model=m.StatusResponse, summary="Daemon, MCP, indexer status and version")
    async def status(request: Request, repo: str | None = Query(default=None, max_length=1024, description=repo_select.REPO_DESC)) -> dict[str, Any]:
        root, _store, served = _sel(repo)
        return collect_status(root, app.state.started_at, os.getpid(), served=served)

    @app.get("/api/v1/graph", response_model=m.GraphResponse, response_model_exclude_none=True,
             summary="Read-only, bounded knowledge-graph slice")
    def graph(  # sync on purpose: runs in the threadpool, not the event loop
        node: str | None = Query(default=None, max_length=512),
        depth: int = Query(default=1, ge=0, le=3),
        limit: int = Query(default=200, ge=1, le=2000),
        repo: str | None = Query(default=None, max_length=1024, description=repo_select.REPO_DESC),
    ) -> dict[str, Any]:
        """Read-only, bounded knowledge-graph slice (never the whole graph)."""
        from interface.tools.graph_view import graph_view  # pylint: disable=import-outside-toplevel
        _root, store, served = _sel(repo)
        return graph_view(node=node, depth=depth, limit=limit, store=None if served else store)

    @app.get("/api/v1/graph/changes", response_model=m.GraphChanges, response_model_exclude_none=True,
             summary="Knowledge-graph change feed since a graph_seq (reset=true: re-fetch /graph)")
    def graph_changes(
        since: int = Query(default=0, ge=0, description="the `seq` of the last response (or `indexer.graph_seq` from /status)"),
        limit: int = Query(default=500, ge=1, le=2000, description="max ops; whole batches only, so a single batch may exceed it"),
        repo: str | None = Query(default=None, max_length=1024, description=repo_select.REPO_DESC),
    ) -> dict[str, Any]:
        from interface.ui import graph_changes as gc  # pylint: disable=import-outside-toplevel
        return gc.changes(_sel(repo)[1], since, limit)

    @app.get("/api/v1/harness", response_model=m.HarnessResponse, summary="Agent clients with CogniRepo configured")
    def harness(repo: str | None = Query(default=None, max_length=1024, description=repo_select.REPO_DESC)) -> dict[str, Any]:
        """Which agent clients have CogniRepo's MCP server configured (names only, no args/env)."""
        from interface.tools.agent_clients import agent_clients  # pylint: disable=import-outside-toplevel
        return agent_clients(_sel(repo)[0])

    @app.get("/api/v1/insights", response_model=m.InsightsInfo, summary="Whether the insights report exists, and when it was generated")
    def insights_info(repo: str | None = Query(default=None, max_length=1024, description=repo_select.REPO_DESC)) -> dict[str, Any]:
        from interface.ui import insights_view  # pylint: disable=import-outside-toplevel
        return insights_view.info(_sel(repo)[0])

    @app.get("/api/v1/insights/report", response_class=HTMLResponse, responses={404: {"model": m.ErrorBody}},
             summary="The insights report HTML, read-only, from its one fixed path")
    def insights_report(download: bool = Query(default=False), repo: str | None = Query(default=None, max_length=1024, description=repo_select.REPO_DESC)) -> Response:
        """Never takes a path. Served sandboxed (no scripts, no network, no forms); ``?download=1`` sends it as an attachment."""
        from interface.ui import insights_view  # pylint: disable=import-outside-toplevel
        path = insights_view.safe_report_file(_sel(repo)[0])
        if path is None:
            return _deny(404, "no_report")
        with open(path, "rb") as fh:
            body = fh.read()
        headers = {
            "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
                                       "frame-ancestors 'self'",
            "X-Frame-Options": "SAMEORIGIN",
        }
        if download:
            headers["Content-Disposition"] = 'attachment; filename="insights.html"'
        return Response(body, media_type="text/html; charset=utf-8", headers=headers)

    stream_counter = app.state.stream_counter = {"n": 0}

    @app.get("/api/v1/events", summary="Live event stream (SSE): tool calls, watcher re-indexes, service actions",
             response_class=StreamingResponse,
             responses={200: {"description": "text/event-stream. `id:` is the event `seq`; send it back as `Last-Event-ID` to resume. "
                                             "A `: heartbeat` comment is sent every 15 s.",
                              "content": {"text/event-stream": {"schema": {"type": "string"}}}},
                        429: {"model": m.ErrorBody, "description": "Too many open streams, or locked out"}})
    async def events_stream(request: Request, session: str | None = Query(default=None, max_length=64),
                            types: str | None = Query(default=None, max_length=200, description="comma-separated globs, e.g. `tool.*,graph.delta`"),
                            replay: int = Query(default=0, ge=0, le=200, description="send the last N events first (ignored with Last-Event-ID)"),
                            last_event_id: str | None = Header(default=None),
                            repo: str | None = Query(default=None, max_length=1024, description=repo_select.REPO_DESC)) -> Response:
        if stream_counter["n"] >= event_stream.MAX_STREAMS:
            return _deny(429, "too_many_streams")
        gen = event_stream.stream(
            request.is_disconnected, _sel(repo)[1],
            after=event_stream.parse_last_event_id(last_event_id), replay=replay, session=session,
            types=events.parse_types(types), counter=stream_counter)
        return StreamingResponse(gen, media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    @app.get("/api/v1/repos", response_model=list[m.RepoEntry],
             summary="Repos CogniRepo has been used on (global registry) with index and watcher state")
    def list_repos() -> list[dict[str, Any]]:
        from interface.ui import repos  # pylint: disable=import-outside-toplevel
        return repos.list_repos(app.state.repo_root)

    @app.get("/api/v1/processes", response_model=list[m.ProcessInfo],
             summary="CogniRepo processes for this repo: this UI server, the watcher, live MCP servers")
    def list_processes(repo: str | None = Query(default=None, max_length=1024, description=repo_select.REPO_DESC)) -> list[dict[str, Any]]:
        from interface.ui import processes  # pylint: disable=import-outside-toplevel
        root, store, served = _sel(repo)
        return processes.list_processes(root, store, include_ui=served)

    @app.get("/api/v1/audit", response_model=list[dict[str, Any]],
             summary="Tail of the control-API audit log (newest last; never contains the token)")
    def audit_tail(tail: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
        return audit.tail(tail) if audit else []

    @app.get("/api/v1/sessions", response_model=list[m.SessionInfo],
             summary="MCP sessions seen in the event log, most recently active first")
    def list_sessions(repo: str | None = Query(default=None, max_length=1024, description=repo_select.REPO_DESC)) -> list[dict[str, Any]]:
        return events.list_sessions(_sel(repo)[1])

    @app.get("/api/v1/sessions/{session_id}", response_model=m.SessionDetail, responses={404: {"model": m.ErrorBody}},
             summary="One session and its last tool calls (oldest first)")
    def session_detail(session_id: str = Path(max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
                       limit: int = Query(default=100, ge=1, le=500), repo: str | None = Query(default=None, max_length=1024, description=repo_select.REPO_DESC)) -> Any:
        store = _sel(repo)[1]
        calls = events.session_calls(store, session_id, limit)
        row = next((r for r in events.list_sessions(store, limit=10**6) if r["id"] == session_id), None)
        if calls is None or row is None:
            return _deny(404, "unknown_session")
        return {**row, "calls": calls}

    @app.get("/api/v1/services", response_model=list[m.ServiceState], summary="State of the allowlisted services")
    def list_services(request: Request, repo: str | None = Query(default=None, max_length=1024, description=repo_select.REPO_DESC)) -> Any:
        denied = _served_or_deny(repo, request, "services")
        return denied if denied is not None else svc.status()

    def _control(action: str, name: str, body: ConfirmBody | None, request: Request) -> JSONResponse:
        client = _client(request)
        origin = request.headers.get("origin")

        def _audit(result: str, **extra: Any) -> None:
            if audit:
                audit.log(f"service_{action}", service=name, result=result, client=client, origin=origin, **extra)

        if name not in ServiceManager.allowed():  # allowlist FIRST — before confirm or any action
            _audit("denied_unknown_service")
            return _deny(404, "unknown_service")
        if body is None or body.confirm is not True:
            _audit("denied_no_confirm")
            return _deny(400, "confirm_required")
        dry = bool(body.dry_run) and action == "start"
        if dry and name != "prune":
            _audit("denied_dry_run_unsupported")
            return _deny(400, "dry_run_unsupported")
        try:
            result = (svc.start(name, dry_run=True) if dry else svc.start(name)) if action == "start" else svc.stop(name)
        except ServiceError as exc:
            _audit("error", code=exc.code)
            return _deny(exc.status, exc.code)
        failed = result.get("state") == "failed"
        _audit("failed" if failed else "ok", state=result.get("state"), changed=result.get("changed"),
               **({"reason": result.get("reason")} if failed else {}))
        return JSONResponse(result)

    @app.post("/api/v1/services/{name}/start", response_model=m.ServiceState, summary="Start an allowlisted service (needs confirm=true)",
              responses={400: {"model": m.ErrorBody}, 404: {"model": m.ErrorBody}, 409: {"model": m.ErrorBody}, 501: {"model": m.ErrorBody}})
    def start_service(name: str, request: Request, body: ConfirmBody | None = Body(default=None),
                      repo: str | None = Query(default=None, max_length=1024, description=repo_select.REPO_DESC)) -> JSONResponse:
        return _served_or_deny(repo, request, "service_start") or _control("start", name, body, request)

    @app.post("/api/v1/services/{name}/stop", response_model=m.ServiceState, summary="Stop an allowlisted service (needs confirm=true)",
              responses={400: {"model": m.ErrorBody}, 404: {"model": m.ErrorBody}, 501: {"model": m.ErrorBody}})
    def stop_service(name: str, request: Request, body: ConfirmBody | None = Body(default=None),
                     repo: str | None = Query(default=None, max_length=1024, description=repo_select.REPO_DESC)) -> JSONResponse:
        return _served_or_deny(repo, request, "service_stop") or _control("stop", name, body, request)

    @app.post("/api/v1/settings/auto-index", response_model=m.AutoIndexState,
              summary="Persist watch.auto_enabled for this repo (needs confirm=true)",
              responses={400: {"model": m.ErrorBody}, 409: {"model": m.ErrorBody}, 422: {"model": m.ErrorBody, "description": "Invalid request body"}})
    def set_auto_index(body: AutoIndexRequest, request: Request, repo: str | None = Query(default=None, max_length=1024, description=repo_select.REPO_DESC)) -> JSONResponse:
        client, origin = _client(request), request.headers.get("origin")
        denied = _served_or_deny(repo, request, "setting_auto_index")
        if denied is not None:
            return denied

        def _audit(result: str, **extra: Any) -> None:
            if audit:
                audit.log("setting_auto_index", enabled=body.enabled, result=result, client=client, origin=origin, **extra)

        if body.confirm is not True:
            _audit("denied_no_confirm")
            return _deny(400, "confirm_required")
        from interface.ui import settings as ui_settings  # pylint: disable=import-outside-toplevel
        try:
            changed = ui_settings.set_auto_index(_store_dir(app.state.repo_root), body.enabled)
        except ui_settings.SettingsError as exc:
            _audit("error", code=exc.code)
            return _deny(409, exc.code)
        _audit("ok", changed=changed)
        return JSONResponse({"auto_index": body.enabled, "changed": changed})

    @app.on_event("startup")
    def _auto_index_on_start() -> None:
        """A repo whose ``watch.auto_enabled`` is explicitly true gets its watcher started with the UI.
        Absent (the default) does nothing here; best-effort and off the request path."""
        import threading  # pylint: disable=import-outside-toplevel
        from interface.ui import settings as ui_settings  # pylint: disable=import-outside-toplevel
        if not ui_settings.explicit_auto_index(_store_dir(app.state.repo_root)):
            return

        def _start() -> None:
            try:
                result = svc.start("watcher")
                if audit:
                    audit.log("auto_index_start", service="watcher", state=result.get("state"))
            except Exception:  # pylint: disable=broad-except
                logging.getLogger(__name__).warning("auto-index watcher start failed", exc_info=True)

        threading.Thread(target=_start, daemon=True, name="cognirepo-ui-auto-index").start()

    @app.get("/_cognirepo/bootstrap.js", include_in_schema=False)
    def bootstrap_js() -> Response:
        """Fragment->cookie swap script (no secrets in it; usable by any console build)."""
        return Response(_BOOTSTRAP_JS, media_type="text/javascript")

    @app.on_event("shutdown")
    def _shutdown() -> None:
        svc.shutdown()

    def _openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
        schema["servers"] = [{"url": "http://127.0.0.1:8731",
                              "description": "Default. The port may differ: see <global dir>/ui/session.json"}]
        schema.setdefault("components", {})["securitySchemes"] = {
            "bearerAuth": {"type": "http", "scheme": "bearer", "description": "Per-session token"},
            "cookieAuth": {"type": "apiKey", "in": "cookie", "name": sec.COOKIE_NAME,
                           "description": "httpOnly SameSite=Strict cookie set by POST /api/v1/session"},
        }
        schema["security"] = [{"bearerAuth": []}, {"cookieAuth": []}]
        guard_responses = {"403": {"description": "Host or Origin header not allowed"},
                           "429": {"description": "Locked out after repeated bad tokens (see Retry-After)"}}
        for path, ops in schema["paths"].items():
            for op in ops.values():
                if path == "/api/v1/session":
                    op["security"] = []  # token travels in the body
                else:
                    op["responses"].setdefault("401", {"description": "Missing or invalid token"})
                for code, spec in guard_responses.items():
                    op["responses"].setdefault(code, spec)
        app.openapi_schema = schema
        return schema

    app.openapi = _openapi  # type: ignore[method-assign]

    if console_dir is not None:
        mount = StaticFiles(directory=console_dir, html=True) if console_dir else None
    else:
        mount = _console_mount()
    if mount is not None:
        app.mount("/", mount, name="console")
    else:
        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def landing() -> str:
            return _FALLBACK_PAGE

    return app


def _console_mount() -> StaticFiles | None:
    """Console to serve: the git-managed, hash-verified ``<global>/console/`` (#215), else the pip
    package, else None (landing page). Offline: resolving never runs git."""
    from interface.ui import console_install  # pylint: disable=import-outside-toplevel
    bundle, reason = console_install.resolve()
    if bundle:
        return console_install.ManifestStaticFiles(bundle)
    if reason:
        logging.getLogger(__name__).warning("git-managed console ignored: %s", reason)
    pip_dir = _console_static_dir()
    return StaticFiles(directory=pip_dir, html=True) if pip_dir else None


def _console_static_dir() -> str | None:
    """Static bundle of the optional ``cognirepo-console`` package (its ``STATIC_DIR``), if installed."""
    import importlib  # pylint: disable=import-outside-toplevel
    try:
        mod = importlib.import_module("cognirepo_console")
    except ImportError:
        return None
    path = getattr(mod, "STATIC_DIR", None)
    return str(path) if path and os.path.isfile(os.path.join(str(path), "index.html")) else None
