# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Global registry of repos CogniRepo has been used on (#210): ``<global dir>/repos.json``.

Why it exists: a repo's store lives in its own ``.cognirepo/`` (or a hashed dir under
``~/.cognirepo/storage/``), so nothing could answer "which repos is cognirepo on?". ``init``,
``index-repo`` and every watcher registration call :func:`register_repo`; the control API's
``GET /api/v1/repos`` reads :func:`load`.

Lives in the global dir, not a repo store, for the same reason ``orgs.json`` does: one list shared by
every repo and every agent process. It holds paths and timestamps only — no content.

``register_repo`` is best-effort (it must never fail ``init`` or a watcher start) and throttled: a
repo seen less than ``_TOUCH_SECS`` ago does not rewrite the file.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

REGISTRY_FILE = "repos.json"
_TOUCH_SECS = 60.0
_MAX_REPOS = 500


def registry_path() -> str:
    from core.config.paths import get_global_dir  # pylint: disable=import-outside-toplevel
    return os.path.join(get_global_dir(), REGISTRY_FILE)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _age_secs(iso: str | None) -> float | None:
    try:
        ts = datetime.strptime(str(iso), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds()
    except ValueError:
        return None


def load() -> list[dict[str, Any]]:
    """Registered repos, most recently seen first. Missing or unreadable file → ``[]``. Never writes."""
    try:
        with open(registry_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    repos = data.get("repos") if isinstance(data, dict) else None
    rows = [r for r in (repos or []) if isinstance(r, dict) and isinstance(r.get("path"), str)]
    return sorted(rows, key=lambda r: str(r.get("last_seen", "")), reverse=True)


def register_repo(repo_path: str, store_dir: str | None = None) -> bool:
    """Record that ``repo_path`` uses CogniRepo. Returns True if the file was written. Never raises."""
    try:
        return _register(os.path.abspath(repo_path), store_dir)
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("repo registry update skipped for %s: %s", repo_path, exc)
        return False


def _register(path: str, store_dir: str | None) -> bool:
    if os.environ.get("COGNIREPO_REPO_REGISTRY", "1").strip().lower() in ("0", "false", "off", "no"):
        return False
    from core.config.atomic import atomic_json_dump  # pylint: disable=import-outside-toplevel
    from core.config.lock import store_lock  # pylint: disable=import-outside-toplevel

    # throttle without taking the lock: the common case is a watcher/index run on a known repo
    for row in load():
        if row["path"] == path:
            age = _age_secs(row.get("last_seen"))
            if age is not None and age < _TOUCH_SECS and (store_dir is None or row.get("store") == store_dir):
                return False
            break

    if store_dir is None:
        from core.config.paths import get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel
        store_dir = get_cognirepo_dir_for_repo(path)
    reg = registry_path()
    os.makedirs(os.path.dirname(reg), exist_ok=True)
    with store_lock(timeout=2.0, lock_path=reg + ".lock"):
        rows = {r["path"]: r for r in load()}
        now = _now()
        prev = rows.get(path, {})
        rows[path] = {"path": path, "store": store_dir, "first_seen": prev.get("first_seen", now), "last_seen": now}
        kept = sorted(rows.values(), key=lambda r: str(r.get("last_seen", "")), reverse=True)[:_MAX_REPOS]
        atomic_json_dump(reg, {"version": 1, "repos": kept}, indent=2, fsync=False)
        try:
            os.chmod(reg, 0o600)
        except OSError:
            pass
    return True


# ── discovery beyond what has registered itself (#210 follow-up) ─────────────────────────────────

SCAN_SKIP = frozenset({".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", ".mypy_cache",
                       "site-packages", "dist", "build", ".cache", ".cognirepo"})
SCAN_MAX_DIRS = 20_000


def is_initialised(path: str) -> bool:
    """True if ``path`` is a repo CogniRepo has a store for (``<store>/config.json`` exists)."""
    try:
        from core.config.paths import get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel
        return os.path.isfile(os.path.join(str(get_cognirepo_dir_for_repo(os.path.abspath(path))), "config.json"))
    except Exception:  # pylint: disable=broad-except
        return False


def register_if_initialised(path: str) -> bool:
    """``register_repo`` for commands that merely *use* a repo (``ui``, ``serve``, ``doctor``, ``prime``):
    an uninitialised directory is not recorded. Best-effort, never raises."""
    return is_initialised(path) and register_repo(path)


def org_repo_paths() -> list[str]:
    """Repo paths linked to any org or project (``<global dir>/orgs.json``). Strictly read-only — unlike
    ``core.config.orgs`` it never backfills ids or creates the global directory."""
    try:
        from core.config.paths import get_global_dir  # pylint: disable=import-outside-toplevel
        with open(os.path.join(get_global_dir(), "orgs.json"), encoding="utf-8") as fh:
            orgs = json.load(fh)
    except (OSError, ValueError):
        return []
    seen: dict[str, None] = {}
    for org in (orgs.values() if isinstance(orgs, dict) else []):
        if not isinstance(org, dict):
            continue
        groups = [org.get("repos")] + [p.get("repos") for p in (org.get("projects") or {}).values()
                                       if isinstance(p, dict)]
        for group in groups:
            for repo in (group if isinstance(group, list) else []):
                if isinstance(repo, str) and repo:
                    seen[os.path.abspath(repo)] = None
    return list(seen)


def known_repos() -> list[dict[str, Any]]:
    """Registry rows plus org-linked repos that are initialised and not already registered."""
    rows = load()
    have = {r["path"] for r in rows}
    for path in org_repo_paths():
        if path not in have and os.path.isdir(path) and is_initialised(path):
            from core.config.paths import get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel
            rows.append({"path": path, "store": str(get_cognirepo_dir_for_repo(path)), "source": "org"})
    return rows


def scan(root: str, depth: int = 3) -> list[str]:
    """Find initialised repos under ``root`` (at most ``depth`` levels down; symlinks and junk directories
    are not entered; at most ``SCAN_MAX_DIRS`` directories are visited). Returns repo paths; registers nothing."""
    root = os.path.abspath(root)
    found: list[str] = []
    visited = 0
    stack = [(root, 0)]
    while stack and visited < SCAN_MAX_DIRS:
        cur, level = stack.pop()
        visited += 1
        if os.path.isfile(os.path.join(cur, ".cognirepo", "config.json")):
            found.append(cur)
        if level >= depth:
            continue
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    if entry.name not in SCAN_SKIP and not entry.name.startswith(".") \
                            and entry.is_dir(follow_symlinks=False):
                        stack.append((entry.path, level + 1))
        except OSError:
            continue
    return sorted(found)


def resolve(ident: str, served_root: str | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """Map a client-supplied repo identifier to a known repo, **only** from the registry, org links and the
    served repo — a client can never name an arbitrary filesystem path. ``ident`` is an exact path or a unique
    directory name. Returns ``(row, None)``, or ``(None, "unknown_repo" | "ambiguous_repo")``."""
    rows = known_repos()
    if served_root:
        cur = os.path.abspath(served_root)
        if all(r["path"] != cur for r in rows):
            from core.config.paths import get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel
            rows.append({"path": cur, "store": str(get_cognirepo_dir_for_repo(cur))})
    by_path = [r for r in rows if r["path"] == ident or (os.path.isabs(ident) and r["path"] == os.path.abspath(ident))]
    if by_path:
        return by_path[0], None
    by_name = [r for r in rows if os.path.basename(r["path"].rstrip(os.sep)) == ident]
    if len(by_name) == 1:
        return by_name[0], None
    return None, ("ambiguous_repo" if by_name else "unknown_repo")
