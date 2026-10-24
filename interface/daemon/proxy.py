# SPDX-FileCopyrightText: 2026 Ashlesh T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""``cognirepo serve`` as a thin MCP proxy to a repo worker (#116).

The proxy speaks stdio MCP to the agent and forwards ``tools/list`` and ``tools/call`` to the worker over its
socket. It imports only the MCP SDK — not faiss, numpy, fastembed or the tool modules — which is where the
per-session memory goes. ``run_proxy`` returns ``False`` *before* it has touched stdio when the daemon cannot be used,
so the caller can run the normal in-process server instead.

Failure rule for a call: if the worker connection is gone before the request is sent, reconnect and retry once; if it
drops after the request was sent we cannot know whether the tool ran, so the agent gets an error saying so and the next
call reconnects. A tool is never silently run twice.
"""
from __future__ import annotations

import logging
import os
import select
import socket
import sys
import threading
from typing import Any

from interface.daemon import client as dclient
from interface.daemon import paths, protocol

logger = logging.getLogger("cognirepo.daemon.proxy")


def peer_closed(sock: socket.socket | None) -> bool:
    """True if the other end has gone away. Between calls the worker never sends anything, so a socket that is
    readable at all is either at EOF (it closed or died) or out of protocol — both mean: do not reuse it."""
    if sock is None:
        return True
    try:
        readable, _, _ = select.select([sock], [], [], 0)
        return bool(readable)           # EOF shows up as "readable"; so would unexpected data
    except (OSError, ValueError):
        return True


class Link:
    """A reconnecting wrapper around ``WorkerLink``, safe to call from the proxy's worker threads."""

    def __init__(self, repo: str) -> None:
        self.repo = repo
        self.client_name: str | None = None
        self._link: dclient.WorkerLink | None = None
        self._lock = threading.Lock()

    def _ensure(self) -> dclient.WorkerLink:
        if self._link is not None and peer_closed(self._link.sock):
            self._link.close()          # the worker died or exited since the last call: nothing was sent, reconnect
            self._link = None
        if self._link is None or self._link.sock is None:
            self._link = dclient.WorkerLink(self.repo, self.client_name).open()
        return self._link

    def call(self, method: str, params: dict[str, Any]) -> Any:
        params = {**params, "client": self.client_name}
        with self._lock:
            for attempt in (1, 2):
                link = self._ensure()
                try:
                    protocol.send(link.sock, protocol.request(method, params, link._next_id + 1))  # pylint: disable=protected-access
                except (OSError, protocol.ProtocolError):
                    link.close()
                    self._link = None
                    if attempt == 2:
                        raise dclient.DaemonUnavailable("lost the connection to the repo worker") from None
                    continue                                   # nothing was sent: safe to reconnect and retry
                link._next_id += 1  # pylint: disable=protected-access
                try:
                    reply = protocol.recv(link.sock)
                    if reply is None:
                        raise protocol.ProtocolError("connection closed before a reply")
                except (OSError, protocol.ProtocolError):
                    link.close()
                    self._link = None
                    raise RuntimeError(
                        "the CogniRepo daemon connection dropped while this call was running; it may or may not "
                        "have been applied. Retry if it is safe to repeat.") from None
                if "error" in reply:
                    err = reply["error"] if isinstance(reply["error"], dict) else {}
                    raise protocol.RpcError(int(err.get("code", protocol.INTERNAL)),
                                            str(err.get("message", "error")), err.get("data"))
                return reply.get("result")
        raise dclient.DaemonUnavailable("unreachable")

    def close(self) -> None:
        if self._link is not None:
            self._link.close()


def can_proxy(project_dir: str | None) -> str | None:
    """The repo root to proxy for, or ``None`` when the daemon should not be used for this launch."""
    if not paths.enabled():
        return None
    repo = os.path.abspath(project_dir or os.getcwd())
    from core.config import repo_registry  # pylint: disable=import-outside-toplevel
    return repo if repo_registry.is_initialised(repo) else None


def run_proxy(project_dir: str | None = None) -> bool:
    """Serve the agent over stdio through the repo worker. ``False`` (nothing printed to stdout, stdio untouched)
    if the daemon cannot be used, so the caller falls back to the in-process server."""
    repo = can_proxy(project_dir)
    if repo is None:
        return False
    link = Link(repo)
    try:
        link._ensure()  # pylint: disable=protected-access
    except dclient.DaemonUnavailable as exc:
        logger.warning("daemon unavailable (%s); serving in-process", exc)
        return False
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("daemon error (%s); serving in-process", exc)
        return False

    import anyio  # pylint: disable=import-outside-toplevel
    from pydantic import TypeAdapter  # pylint: disable=import-outside-toplevel
    from mcp import types  # pylint: disable=import-outside-toplevel
    from mcp.server.fastmcp.exceptions import ToolError  # pylint: disable=import-outside-toplevel
    from mcp.server.lowlevel import Server  # pylint: disable=import-outside-toplevel
    from mcp.server.stdio import stdio_server  # pylint: disable=import-outside-toplevel
    from core.config.version import __version__  # pylint: disable=import-outside-toplevel

    server: Server = Server("cognirepo", version=__version__)
    block = TypeAdapter(types.ContentBlock)

    def note_client() -> None:
        if link.client_name is None:
            try:
                info = server.request_context.session.client_params.clientInfo
                link.client_name = " ".join(str(info.name).split())[:64] or None
            except Exception:  # pylint: disable=broad-except
                pass

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        note_client()
        try:
            raw = await anyio.to_thread.run_sync(link.call, "tools.list", {})
        except Exception as exc:  # pylint: disable=broad-except
            raise ToolError(f"CogniRepo daemon unavailable: {exc}") from exc
        return [types.Tool.model_validate(t) for t in raw]

    @server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: dict[str, Any]):
        note_client()
        try:
            res = await anyio.to_thread.run_sync(link.call, "tools.call", {"name": name, "arguments": arguments or {}})
        except protocol.RpcError as exc:
            raise ToolError(exc.message) from exc
        except Exception as exc:  # pylint: disable=broad-except
            raise ToolError(str(exc)) from exc
        content = None if res.get("content") is None else [block.validate_python(b) for b in res["content"]]
        structured = res.get("structured")
        if content is not None and structured is not None:
            return content, structured
        return content if content is not None else structured

    async def _serve() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    try:
        anyio.run(_serve)
    except Exception:  # pylint: disable=broad-except
        # stdio is already ours: falling back to a second server on it would corrupt the session
        logger.exception("proxy session ended with an error")
    finally:
        link.close()
    return True


def main() -> int:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    return 0 if run_proxy(os.getcwd()) else 1


if __name__ == "__main__":
    sys.exit(main())
