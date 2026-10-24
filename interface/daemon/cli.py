# SPDX-FileCopyrightText: 2026 Ashlesh T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""``cognirepo daemon start|stop|status|restart`` (#116)."""
from __future__ import annotations

import json
import sys
from typing import Any

from interface.daemon import client, paths


def _mb(n: Any) -> str:
    return f"{int(n) / 1048576:.0f} MB" if isinstance(n, (int, float)) else "?"


def render_status(st: dict[str, Any] | None) -> str:
    if st is None:
        return "cognirepod: not running"
    lines = [f"cognirepod {st['version']} — pid {st['pid']}, {_mb(st.get('rss_bytes'))}, socket {st['socket']}",
             f"workers: {len(st['workers'])} of {st.get('max_workers')}"]
    for w in st["workers"]:
        state = "unresponsive" if w.get("unresponsive") else ("up" if w.get("alive") else "exited")
        lines.append(f"  {w['repo']}  pid {w['pid']}  {state}  clients {w.get('clients', '?')}  "
                     f"calls {w.get('calls', '?')}  {_mb(w.get('rss_bytes'))}  idle {w.get('idle_secs', '?')}s")
    return "\n".join(lines)


def run(args: Any) -> int:
    cmd = getattr(args, "daemon_command", None) or "status"
    if not paths.SUPPORTED:
        print("cognirepod needs Unix domain sockets, which this platform does not provide; "
              "`cognirepo serve` keeps running in-process.", file=sys.stderr)
        return 2
    try:
        if cmd in ("start", "restart"):
            if cmd == "restart":
                client.stop()
            info = client.ensure_supervisor()
            print(f"cognirepod {info['version']} running (pid {info['pid']}). "
                  f"Agents use it when daemon.enabled is on (COGNIREPO_DAEMON=1).")
            return 0
        if cmd == "stop":
            print("cognirepod stopped." if client.stop() else "cognirepod: not running.")
            return 0
        st = client.status()
        if getattr(args, "json", False):
            print(json.dumps(st if st is not None else {"running": False}))
        else:
            print(render_status(st))
            if st is None and paths.enabled():
                print("(daemon.enabled is on: the first `cognirepo serve` starts it)")
        return 0
    except client.DaemonUnavailable as exc:
        print(f"cognirepod: {exc}", file=sys.stderr)
        return 1
