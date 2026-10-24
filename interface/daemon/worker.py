# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""A daemon repo worker: the normal server code with ONE repo fixed, serving many agents over a Unix socket (#116).

``python -m interface.daemon.worker --repo R --socket S``. Started by the supervisor, never by hand. Each connection is
one agent session: it gets its own ``ClientSession`` (so session ids, client names and call counts stay per agent),
and its tool calls run through the same FastMCP tool functions the stdio server uses — the worker only replaces the
transport. It exits by itself once it has had no connection for ``daemon.worker_idle_secs``.
"""
from __future__ import annotations

import argparse
import asyncio
import gc
import logging
import os
import signal
import sys
import threading
import time
from typing import Any

from interface.daemon import protocol
from interface.daemon.rpc_server import Connection, RpcServer

logger = logging.getLogger("cognirepo.daemon.worker")


def encode_result(res: Any) -> dict[str, Any]:
    """FastMCP's ``call_tool`` returns content blocks, a ``(content, structured)`` pair or a bare dict — keep all three."""
    content, structured = None, None
    if isinstance(res, tuple):
        content, structured = res
    elif isinstance(res, dict):
        structured = res
    else:
        content = res
    return {"content": None if content is None else [b.model_dump(mode="json", exclude_none=True) for b in content],
            "structured": structured}


def trim_memory() -> None:
    """Return freed memory to the OS: collect cyclic garbage, then ``malloc_trim`` where glibc has it.

    A tool call that fails (or builds big temporaries) leaves reference cycles holding hundreds of MB until the
    cyclic GC next runs; measured on a worker after two failed ``context_pack`` calls: 561 MB, 349 MB after
    ``gc.collect()``, 290 MB after ``malloc_trim``. Called when the worker has been quiet, never on the request path."""
    gc.collect()
    try:
        import ctypes  # pylint: disable=import-outside-toplevel
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


_TRIM_AFTER_QUIET_SECS = 3.0


class Worker:
    def __init__(self, repo: str, sock_path: str, idle_secs: float) -> None:
        from interface.server import mcp_server  # pylint: disable=import-outside-toplevel
        from interface.server import client_session  # pylint: disable=import-outside-toplevel
        from core.config.version import __version__  # pylint: disable=import-outside-toplevel
        self.ms = mcp_server
        self.cs_mod = client_session
        self.version = __version__
        self.repo = repo
        self.idle_secs = idle_secs
        self.started = time.time()
        self.last_activity = time.time()
        self.calls = 0
        self._trimmed_at_calls = 0
        self._lock = threading.Lock()
        # An in-process `serve` runs one tool at a time (FastMCP calls sync tools inline on its event loop); a worker
        # shares one process between agents, and unbounded parallel tool calls multiplied its transient memory
        # (measured: 5 concurrent agents -> a 954 MB worker vs 346 MB for one serve). Bound the parallelism.
        from interface.daemon import paths  # pylint: disable=import-outside-toplevel
        self._gate = threading.BoundedSemaphore(max(1, int(paths.setting("worker_concurrency"))))
        self.server = RpcServer(sock_path, {
            "hello": self.h_hello, "ping": lambda c, p: "pong", "session.open": self.h_session_open,
            "tools.list": self.h_tools_list, "tools.call": self.h_tools_call,
            "status": self.h_status, "shutdown": self.h_shutdown,
        }, name="worker", on_disconnect=self.on_disconnect)

    # -- per-connection session -----------------------------------------------------------------
    def _session(self, conn: Connection):
        cs = conn.state.get("cs")
        if cs is None:
            raise protocol.RpcError(protocol.INVALID_REQUEST, "open a session first (session.open)")
        return cs

    def _in_session(self, cs, fn):
        token = self.cs_mod.CURRENT.set(cs)
        try:
            return fn()
        finally:
            self.cs_mod.CURRENT.reset(token)

    def _set_client(self, cs, params: dict[str, Any]) -> None:
        name = params.get("client")
        if isinstance(name, str) and name and cs.client is None:
            cs.client = " ".join(name.split())[:64] or None

    # -- handlers -------------------------------------------------------------------------------
    def h_hello(self, _conn, params):
        theirs = params.get("version")
        if theirs and theirs != self.version:
            raise protocol.RpcError(protocol.VERSION_MISMATCH, f"worker is {self.version}, client is {theirs}",
                                    {"worker_version": self.version})
        return {"version": self.version, "pid": os.getpid(), "repo": self.repo, "started": self.started}

    def h_session_open(self, conn, params):
        if conn.state.get("cs") is not None:
            return {"session_id": conn.state["cs"].session_id}
        from intelligence.orchestrator.session import create_session  # pylint: disable=import-outside-toplevel
        cs = self.cs_mod.ClientSession(mcp_session=create_session(model="mcp-server"))
        self._set_client(cs, params)
        conn.state["cs"] = cs
        self._in_session(cs, lambda: self.ms._emit_session_event("session.start"))  # pylint: disable=protected-access
        self._touch()
        return {"session_id": cs.session_id}

    def h_tools_list(self, conn, params):
        cs = self._session(conn)
        self._set_client(cs, params)
        self._in_session(cs, self.ms._announce_client)  # pylint: disable=protected-access
        self._touch()
        tools = asyncio.run(self.ms.mcp.list_tools())
        return [t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in tools]

    def h_tools_call(self, conn, params):
        cs = self._session(conn)
        name, args = params.get("name"), params.get("arguments") or {}
        if not isinstance(name, str) or not isinstance(args, dict):
            raise protocol.RpcError(protocol.INVALID_PARAMS, "tools.call needs a name and an arguments object")
        self._set_client(cs, params)
        self._touch()
        with self._lock:
            self.calls += 1
        from mcp.server.fastmcp.exceptions import ToolError  # pylint: disable=import-outside-toplevel

        def run():
            self.ms._announce_client()  # pylint: disable=protected-access
            return asyncio.run(self.ms.mcp.call_tool(name, args))

        try:
            with self._gate:
                return encode_result(self._in_session(cs, run))
        except ToolError as exc:
            raise protocol.RpcError(protocol.TOOL_ERROR, str(exc)) from exc
        finally:
            self._touch()

    def clients(self) -> int:
        """Agents with an open session. (A bare connection — e.g. the supervisor asking for ``status`` — is not one.)"""
        with self.server._lock:  # pylint: disable=protected-access
            return sum(1 for c in self.server.connections if c.state.get("cs") is not None)

    def h_status(self, _conn, _params):
        rss = None
        try:
            import psutil  # pylint: disable=import-outside-toplevel
            rss = int(psutil.Process().memory_info().rss)
        except Exception:  # pylint: disable=broad-except
            pass
        return {"repo": self.repo, "pid": os.getpid(), "version": self.version, "started": self.started,
                "clients": self.clients(), "calls": self.calls, "rss_bytes": rss,
                "idle_secs": round(time.time() - self.last_activity, 1)}

    def h_shutdown(self, _conn, _params):
        threading.Thread(target=self.stop, daemon=True).start()
        return {"stopping": True}

    def on_disconnect(self, conn: Connection) -> None:
        cs = conn.state.get("cs")
        if cs is not None:
            self._in_session(cs, lambda: self.ms._emit_session_event("session.end"))  # pylint: disable=protected-access
        self._touch()

    # -- lifecycle ------------------------------------------------------------------------------
    def _touch(self) -> None:
        self.last_activity = time.time()

    def stop(self) -> None:
        self.server.stop()

    def run(self) -> int:
        self.server.start()
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        signal.signal(signal.SIGINT, lambda *_: self.stop())
        logger.info("worker for %s listening on %s (pid %s)", self.repo, self.server.path, os.getpid())
        while not self.server.stopped:
            time.sleep(1.0)
            quiet = time.time() - self.last_activity
            if self.calls != self._trimmed_at_calls and quiet > _TRIM_AFTER_QUIET_SECS:
                self._trimmed_at_calls = self.calls            # once per burst of activity, off the request path
                trim_memory()
            if self.clients() == 0 and quiet > self.idle_secs:
                logger.info("worker for %s idle for %.0fs: exiting", self.repo, self.idle_secs)
                self.stop()
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m interface.daemon.worker")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--idle-secs", type=float, default=600.0)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s %(message)s")
    repo = os.path.abspath(args.repo)
    from interface.server import mcp_server  # pylint: disable=import-outside-toplevel
    os.chdir(repo)                                  # relative-path code (and `git`) behave as under `serve`
    mcp_server._prepare_runtime(repo)  # pylint: disable=protected-access
    mcp_server._start_background_services()  # pylint: disable=protected-access
    return Worker(repo, args.socket, args.idle_secs).run()


if __name__ == "__main__":
    sys.exit(main())
