# SPDX-FileCopyrightText: 2026 Ashlesh T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Graph-backend state, toggle and migration for the control API and ``cognirepo graph backend`` (#115 follow-up).

``state()`` is strictly read-only and is the single source of truth the console renders — it never guesses:
what is configured, what is actually in force in this process (the env override and encryption can differ), what
each backend's file holds, whether switching would show stale data, and what to recommend. ``GraphBackendJob``
runs ``cognirepo graph migrate`` as a detached job (fixed argv, nothing from a request reaches it except the
validated backend name and two booleans), so a long copy survives the request and the console polls it.
"""
from __future__ import annotations

import json
import os
import subprocess  # nosec B404
import sys
from typing import Any

from data.graph import backend as gb

JOB = "graph-migrate"
DRY_RUN_TIMEOUT_SECS = 180
EXIT_BUSY = 75


def _sessions(repo_root: str, store: str) -> int:
    try:
        from interface.ui import processes  # pylint: disable=import-outside-toplevel
        return len([r for r in processes.list_processes(repo_root, store, include_ui=False) if r["role"] == "mcp"])
    except Exception:  # pylint: disable=broad-except
        return 0


def state(repo_root: str, store: str, job: dict | None = None) -> dict[str, Any]:
    """Everything the console needs to render the toggle, the migrate panel and the recommendation."""
    res = gb.resolve(store)
    files = gb.graph_files(store)
    counts = gb.graph_counts(store)
    encrypted = gb.encryption_on(store)
    sessions = _sessions(repo_root, store)
    rec = gb.recommend(counts[0] if counts else None, sessions, encrypted)
    other = gb.SQLITE if res.backend == gb.NETWORKX else gb.NETWORKX
    initialised = os.path.isfile(os.path.join(store, "config.json"))
    env = gb.env_override()
    blocker = None
    if not initialised:
        blocker = "not_initialised"
    elif job and job.get("state") == "running":
        blocker = "job_running"
    elif env:
        blocker = "env_override"           # COGNIREPO_GRAPH_BACKEND in the server's environment wins over the file
    elif other == gb.SQLITE and encrypted:
        blocker = "encryption_on"
    return {
        "active": res.backend, "configured": gb.configured(store), "env_override": env or None,
        "forced_by_encryption": res.requested == gb.SQLITE and res.backend == gb.NETWORKX and encrypted,
        "note": res.note or None,
        "files": files, "nodes": counts[0] if counts else None, "edges": counts[1] if counts else None,
        "stale_note": gb.stale_note(store) or None,
        "recommendation": {"use": rec.use, "confidence": rec.confidence, "reasons": rec.reasons},
        "sessions": sessions,
        "can_toggle": blocker is None, "toggle_blocker": blocker,
        "switch_to": other,
        "switch_needs_migration": blocker is None and gb.needs_migration(store, other),
        "job": job,
    }


def _argv(to: str, replace: bool = False, dry_run: bool = False) -> list[str]:
    argv = [sys.executable, "-m", "interface.cli.main", "graph", "migrate", "--to", to, "--json", "--stop-watcher"]
    if replace:
        argv.append("--replace")
    if dry_run:
        argv.append("--dry-run")
    return argv


def last_json(text: str, key: str) -> dict | None:
    """The last line of *text* that is a JSON object containing *key*."""
    for line in reversed([ln for ln in text.splitlines() if ln.strip().startswith("{")]):
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and key in data:
            return data
    return None


def classify(rc: int | None, text: str) -> tuple[str, str | None, Any]:
    """FileJob classifier: (result, reason, summary)."""
    final = last_json(text, "result")
    if rc == 0 and final and final.get("result") == "ok":
        return "ok", None, final.get("summary")
    if rc == EXIT_BUSY or (final and final.get("code") == "busy"):
        return "busy", "store_busy", final
    if final and final.get("code"):
        return "failed", str(final["code"]), final
    return "failed", "migrate_failed", final


class GraphBackendJob:
    """The detached ``graph migrate`` run for one served repo."""

    def __init__(self, repo_root: str, store: str) -> None:
        from interface.ui.jobs import FileJob  # pylint: disable=import-outside-toplevel
        self.repo_root = repo_root
        # NOT the watchers/ directory: the CLI's watcher lookup globs watchers/*.json and would mistake this job's
        # run record (pid + cwd = the repo) for a watcher of the repo, then stop the migration itself
        self.job = FileJob(JOB, os.path.join(store, "jobs"), classify)

    def view(self) -> dict[str, Any]:
        """``{state, last_run, summary, progress}``; progress is the latest phase line the CLI printed."""
        view = self.job.view()
        # pylint: disable=protected-access
        progress = last_json(self.job._log(), "phase") if view["state"] == "running" else None
        return {**view, "progress": progress}

    def start(self, to: str, replace: bool) -> bool:
        return self.job.start(_argv(to, replace), self.repo_root)

    def dry_run(self, to: str) -> dict[str, Any]:
        """Run ``graph migrate --dry-run --json`` and return its plan (nothing is changed)."""
        try:
            proc = subprocess.run(  # nosec B603 — fixed argv, backend name validated by the caller
                _argv(to, dry_run=True), cwd=self.repo_root, capture_output=True, text=True,
                timeout=DRY_RUN_TIMEOUT_SECS, check=False, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"result": "error", "code": "spawn_failed", "message": str(exc)[:300]}
        final = last_json(proc.stdout, "result")
        return final or {"result": "error", "code": "plan_failed",
                         "message": (proc.stderr or proc.stdout).strip()[-300:]}
