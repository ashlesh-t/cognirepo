# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Find cognirepo processes that are no longer doing anything useful (COGNIREPO-119).

Background: 12 — later 80 — ``python -m interface.cli.main init`` processes were found alive for
days, ~40 MB each. They were not stuck ``init`` runs: ``init`` starts a background watcher by forking
itself, and a forked daemon keeps its parent's command line. They were watchers whose repo (a temp
directory of a test run) had been deleted, reparented to ``systemd --user``, and nothing ever told
them to stop. The watcher now exits when its directory disappears; this module lets ``cognirepo
doctor`` see the ones that already exist (or have another cause) and say how to remove them.

Linux ``/proc`` only; elsewhere ``scan()`` returns an empty list.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

#: one-shot commands: still running after this long means hung, not busy
ONE_SHOT_MAX_AGE_SECS = 6 * 3600
_ONE_SHOT = {"init", "index-repo", "setup", "doctor", "prime", "verify-index", "insights"}


@dataclass
class CogniProc:
    pid: int
    ppid: int
    age_secs: float
    rss_mb: float
    command: str            # the cognirepo subcommand ("watch", "init", "serve", …) or "?"
    cwd: str
    cwd_deleted: bool


def _command_of(argv: "list[str]") -> "str | None":
    """The cognirepo subcommand if ``argv`` is a cognirepo CLI process, else None."""
    for i, a in enumerate(argv):
        if a.endswith("interface.cli.main") or os.path.basename(a) == "cognirepo":
            rest = [x for x in argv[i + 1:] if not x.startswith("-")]
            return rest[0] if rest else "?"
    return None


def scan(proc_root: str = "/proc") -> "list[CogniProc]":
    """All running cognirepo CLI processes (excluding this one), via /proc."""
    if not os.path.isdir(proc_root):
        return []
    try:
        hz = os.sysconf("SC_CLK_TCK")
        page = os.sysconf("SC_PAGE_SIZE")
        with open(os.path.join(proc_root, "uptime"), encoding="ascii") as fh:
            uptime = float(fh.read().split()[0])
    except (OSError, ValueError):
        return []
    me = os.getpid()
    out: "list[CogniProc]" = []
    for name in os.listdir(proc_root):
        if not name.isdigit() or int(name) == me:
            continue
        base = os.path.join(proc_root, name)
        try:
            with open(os.path.join(base, "cmdline"), "rb") as fh:
                argv = [a.decode("utf-8", "replace") for a in fh.read().split(b"\0") if a]
            cmd = _command_of(argv)
            if cmd is None:
                continue
            with open(os.path.join(base, "stat"), encoding="utf-8") as fh:
                fields = fh.read().rsplit(")", 1)[1].split()
            if fields[0] == "Z":
                continue                                       # a zombie holds no memory
            ppid, start_ticks, rss_pages = int(fields[1]), int(fields[19]), int(fields[21])
            try:
                cwd = os.readlink(os.path.join(base, "cwd"))
            except OSError:
                cwd = ""
            deleted = cwd.endswith(" (deleted)")
            out.append(CogniProc(
                pid=int(name), ppid=ppid, age_secs=max(0.0, uptime - start_ticks / hz),
                rss_mb=rss_pages * page / (1024 * 1024), command=cmd,
                cwd=cwd[: -len(" (deleted)")] if deleted else cwd, cwd_deleted=deleted,
            ))
        except (OSError, IndexError, ValueError):
            continue                                           # exited while we looked
    return out


def find_stale(procs: "list[CogniProc]") -> "list[tuple[CogniProc, str]]":
    """Processes that should not still be running, each with the reason.

    * its working directory was deleted — a watcher/indexer for a repo that no longer exists
      (an MCP ``serve`` is never reported: it belongs to a live agent session);
    * a one-shot command (``init``, ``index-repo`` …) that is still running after 6 hours.
    """
    stale: "list[tuple[CogniProc, str]]" = []
    for p in procs:
        if p.command == "serve":
            continue
        if p.cwd_deleted:
            stale.append((p, f"its directory was deleted ({p.cwd})"))
        elif p.command in _ONE_SHOT and p.age_secs > ONE_SHOT_MAX_AGE_SECS:
            stale.append((p, f"`{p.command}` has been running for {p.age_secs / 3600:.0f} h"))
    return stale


def describe(stale: "list[tuple[CogniProc, str]]") -> "tuple[str, str]":
    """(message, hint) for doctor."""
    total = sum(p.rss_mb for p, _ in stale)
    pids = " ".join(str(p.pid) for p, _ in stale)
    msg = f"{len(stale)} stale cognirepo process(es) using ~{total:.0f} MB (e.g. pid {stale[0][0].pid}: {stale[0][1]})"
    return msg, f"Stop them: kill {pids}"


__all__ = ["CogniProc", "ONE_SHOT_MAX_AGE_SECS", "describe", "find_stale", "scan"]
