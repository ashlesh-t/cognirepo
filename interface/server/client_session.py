# SPDX-FileCopyrightText: 2026 Ashlesh T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Per-client state for a server that serves more than one agent (the daemon's repo worker, #116).

A plain ``cognirepo serve`` has exactly one client for its whole life, so ``mcp_server`` keeps that client's session
id, name and call count in module globals. A worker shares one process between many clients, so the same four
facts must be looked up per request: the worker puts the connection's ``ClientSession`` in ``CURRENT`` (a
ContextVar, so it follows the request into the thread/event loop that runs the tool) and ``mcp_server`` prefers it
over the globals when it is set.
"""
from __future__ import annotations

import threading
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class ClientSession:
    mcp_session: dict | None = None      # the conversation log from intelligence.orchestrator.session
    client: str | None = None            # MCP clientInfo.name
    call_count: int = 0                  # tool.start + tool.shed seen for this client
    ended: bool = False
    announced: bool = False              # session.client event written
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def session_id(self) -> str | None:
        return (self.mcp_session or {}).get("session_id")


CURRENT: ContextVar[ClientSession | None] = ContextVar("cognirepo_client_session", default=None)
