# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Read-only view of the optional per-user daemon (#116) for ``GET /api/v1/daemon`` and the repo list (#120).

Never starts anything: it asks a *running* supervisor for ``status`` with a short timeout, so a wedged or absent
daemon makes the API answer ``running: false`` quickly instead of hanging the console.
"""
from __future__ import annotations

import os
from typing import Any

_TIMEOUT_SECS = 1.5


def daemon_state(served_root: str | None = None) -> dict[str, Any]:
    from interface.daemon import client, paths  # pylint: disable=import-outside-toplevel
    st = client.status(timeout=_TIMEOUT_SECS) if paths.SUPPORTED else None
    served = os.path.abspath(served_root) if served_root else None
    out: dict[str, Any] = {"supported": bool(paths.SUPPORTED), "enabled": bool(paths.enabled()),
                           "running": st is not None, "version": None, "pid": None, "rss_bytes": None, "socket": None,
                           "max_workers": None, "started": None, "workers": []}
    if st is not None:
        out.update(version=st.get("version"), pid=st.get("pid"), rss_bytes=st.get("rss_bytes"),
                   socket=st.get("socket"), max_workers=st.get("max_workers"), started=st.get("started"))
        out["workers"] = [{
            "repo": w.get("repo"), "pid": w.get("pid"), "alive": bool(w.get("alive")),
            "unresponsive": bool(w.get("unresponsive", False)), "clients": w.get("clients"), "calls": w.get("calls"),
            "rss_bytes": w.get("rss_bytes"), "idle_secs": w.get("idle_secs"), "started": w.get("started"),
            "served": served is not None and w.get("repo") == served,
        } for w in st.get("workers", [])]
    return out


def workers_by_repo() -> dict[str, dict[str, Any]]:
    """``{repo root: worker row}`` for the repo list; empty when the daemon is not running."""
    return {w["repo"]: w for w in daemon_state()["workers"] if w.get("repo")}
