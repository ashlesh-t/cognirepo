# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Run the control API with uvicorn. Foreground; ``cognirepo ui`` spawns it detached."""
from __future__ import annotations

import os
import socket
import sys
from dataclasses import dataclass
from typing import Any

from interface.ui import security as sec
from interface.ui.app import create_app
from interface.ui.audit import AuditLog
from interface.ui.session import clear_session, write_session

DEFAULT_PORT = 8731


@dataclass
class Built:
    server: Any          # uvicorn.Server
    sock: socket.socket
    token: str
    port: int
    host: str
    audit: AuditLog


def _bind(host: str, port: int, explicit_port: bool) -> socket.socket:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError:
        if explicit_port or port == 0:
            sock.close()
            raise
        sock.bind((host, 0))  # default port busy: fall back to a free one
    sock.listen(64)
    return sock


def build(repo_root: str, host: str = "127.0.0.1", port: int | None = None, unsafe_bind: bool = False,
          allow_origins: tuple[str, ...] = (), token: str | None = None) -> Built:
    """Validate the bind, bind the socket, and assemble the app. Raises UnsafeBindError."""
    import uvicorn  # pylint: disable=import-outside-toplevel
    from core.config.paths import get_global_path  # pylint: disable=import-outside-toplevel

    warning = sec.validate_bind_host(host, unsafe_bind)
    if warning:
        print(warning, file=sys.stderr)
    sock = _bind(host, DEFAULT_PORT if port is None else port, explicit_port=port is not None)
    actual_port = sock.getsockname()[1]
    token = token or sec.new_token()
    cfg = sec.SecurityConfig(token=token, port=actual_port, extra_origins=tuple(allow_origins))
    audit = AuditLog(get_global_path("ui/audit.log"))
    app = create_app(cfg, repo_root, audit)
    config = uvicorn.Config(app, log_level="warning", access_log=False, lifespan="on")
    return Built(uvicorn.Server(config), sock, token, actual_port, host, audit)


def serve(repo_root: str, host: str = "127.0.0.1", port: int | None = None, unsafe_bind: bool = False,
          allow_origins: tuple[str, ...] = ()) -> int:
    """Blocking entry point behind ``cognirepo ui --serve``. Returns a process exit code."""
    try:
        built = build(repo_root, host, port, unsafe_bind, allow_origins)
    except sec.UnsafeBindError as exc:
        print(f"cognirepo ui: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"cognirepo ui: cannot start: {exc}", file=sys.stderr)
        return 1
    pid = os.getpid()
    write_session(built.token, built.host, built.port, pid, os.path.abspath(repo_root))
    built.audit.log("server_start", host=built.host, port=built.port, repo=os.path.abspath(repo_root),
                    unsafe_bind=unsafe_bind, pid=pid)
    try:
        built.server.run(sockets=[built.sock])
    finally:
        built.audit.log("server_stop", pid=pid)
        clear_session(only_pid=pid)
        built.sock.close()
    return 0
