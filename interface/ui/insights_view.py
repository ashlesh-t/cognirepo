# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Read-only access to the insights report for ``GET /api/v1/insights[/report]`` (#147).

There is exactly ONE file this can ever return: ``interface.tools.insights.report_path(repo)``.
No client-supplied path, name or query reaches the filesystem. On top of that the file must be a
regular file whose real path is still inside the repo's ``.claude/insights`` directory, so a symlink
planted at (or above) the report path cannot turn this into an arbitrary-file read.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any

from interface.tools.insights import report_path

#: refuse to serve anything bigger (a runaway/forged file) — real reports are tens of KB
MAX_REPORT_BYTES = 8 * 1024 * 1024
_GENERATED_AT_RE = re.compile(rb'<meta name="cognirepo:generated-at" content="([^"]*)">')


def safe_report_file(repo_root: str) -> str | None:
    """Absolute path of the report if it exists and is safe to serve, else None."""
    path = report_path(os.path.abspath(repo_root))
    # Resolve only the repo root (it may legitimately be a symlink). Everything below it must be the
    # literal .claude/insights/<name>, so a symlinked directory or file anywhere under it fails the
    # equality below instead of being quietly followed.
    expected = os.path.join(os.path.realpath(repo_root), ".claude", "insights", os.path.basename(path))
    try:
        if os.path.islink(path) or not os.path.isfile(path):
            return None
        real = os.path.realpath(path)
        if real != expected or os.path.getsize(real) > MAX_REPORT_BYTES:
            return None
    except OSError:
        return None
    return real


def info(repo_root: str) -> dict[str, Any]:
    """``{exists, generated_at, bytes}``; ``generated_at`` is the report's own stamp, else its mtime."""
    path = safe_report_file(repo_root)
    if path is None:
        return {"exists": False, "generated_at": None, "bytes": 0}
    stamp = None
    try:
        with open(path, "rb") as fh:
            m = _GENERATED_AT_RE.search(fh.read(16384))
        if m:
            stamp = m.group(1).decode("utf-8", "replace")
        if stamp is None:
            stamp = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).isoformat()
        size = os.path.getsize(path)
    except OSError:
        return {"exists": False, "generated_at": None, "bytes": 0}
    return {"exists": True, "generated_at": stamp, "bytes": size}
