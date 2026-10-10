# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
What the post-commit hook leaves behind, and how to read it (COGNIREPO-123).

The hook used to run ``cognirepo index-repo --files … 2>/dev/null &``: every failure — a pipx
venv that had lost ``keyring`` so no encrypted graph could be saved, a missing ``cognirepo``, a
refused save — was discarded, and ``graph.pkl`` stayed absent for days without anyone noticing.

The hook now appends everything to ``<store>/hook.log`` (rotated at 256 KiB, one ``.1`` kept) and
records the outcome of its last run in ``<store>/hook.last`` as ``key=value`` lines::

    ts=2026-10-06T17:21:04Z
    exit=1
    files=2

All of that is written by the *shell* hook itself, deliberately not by a ``cognirepo`` subcommand:
the failure it reports can be exactly that ``cognirepo`` does not start. This module is the reader
used by ``doctor`` and ``get_session_brief``.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

HOOK_LOG = "hook.log"
HOOK_LAST = "hook.last"
_MARKER = re.compile(r"^--- \d{4}-\d{2}-\d{2}T")     # the line the hook writes before each run
_EXIT_LINE = re.compile(r"^exit=\d+\s*$")


@dataclass
class HookRun:
    ts: str
    exit_code: int
    files: int
    reason: str          # last meaningful output line of a failed run ('' if it succeeded)
    log_path: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def describe(self) -> str:
        n = f"{self.files} file(s)" if self.files else "no files"
        if self.ok:
            return f"last run OK ({self.ts}, {n})"
        why = f": {self.reason}" if self.reason else ""
        return f"last run FAILED (exit {self.exit_code} at {self.ts}, {n}){why}"


def _parse_kv(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if "=" in line:
            key, _, val = line.partition("=")
            out[key.strip()] = val.strip()
    return out


def failure_reason(log_text: str, max_len: int = 200) -> str:
    """Last meaningful line of the most recent run in a hook.log (e.g. the final traceback line)."""
    lines = log_text.splitlines()
    start = 0
    for i, line in enumerate(lines):
        if _MARKER.match(line):
            start = i + 1
    for line in reversed(lines[start:]):
        line = line.strip()
        if line and not _EXIT_LINE.match(line):
            return line[:max_len]
    return ""


def read_last_run(*store_dirs: "str | None") -> "HookRun | None":
    """The most recently written ``hook.last`` among ``store_dirs`` (missing/garbled → skipped)."""
    best: "tuple[float, HookRun] | None" = None
    for d in dict.fromkeys(x for x in store_dirs if x):          # unique, order kept
        last = os.path.join(d, HOOK_LAST)
        try:
            with open(last, encoding="utf-8") as fh:
                kv = _parse_kv(fh.read())
            code = int(kv["exit"])
            mtime = os.path.getmtime(last)
        except (OSError, KeyError, ValueError):
            continue
        log_path = os.path.join(d, HOOK_LOG)
        reason = ""
        if code != 0:
            try:
                with open(log_path, encoding="utf-8", errors="replace") as fh:
                    fh.seek(0, os.SEEK_END)
                    size = fh.tell()
                    fh.seek(max(0, size - 16384))          # only the tail is needed
                    reason = failure_reason(fh.read())
            except OSError:
                pass
        try:
            files = int(kv.get("files", 0))
        except ValueError:
            files = 0
        run = HookRun(kv.get("ts", "unknown time"), code, files, reason, log_path)
        if best is None or mtime > best[0]:
            best = (mtime, run)
    return best[1] if best else None


def hook_is_outdated(hook_text: str, current_block: str, sentinel_start: str) -> bool:
    """True if a post-commit hook has a cognirepo block that is not the current one."""
    return sentinel_start in hook_text and current_block not in hook_text
