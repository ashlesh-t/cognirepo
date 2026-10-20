# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Git-managed Engram console under ``<global>/console/`` (#215).

The console is a prebuilt static bundle published on the ``release`` branch of its own repo, with a
``console.json`` manifest (version, ``api_major``, sha256 of every file). This module

* **resolves** the bundle for the server (``resolve`` — read-only, never touches the network),
* **installs** it on ``cognirepo ui`` when missing (``ensure`` — the only place that runs ``git``),
* **validates** it: manifest shape, ``api_major`` equal to this server's, every file's sha256, no
  path escapes or symlinks. Only files the manifest lists are ever served (``ManifestStaticFiles``).

Threat model, stated plainly: the hashes catch local corruption and tampering of an installed
bundle. They do not authenticate the repo itself — the manifest travels in the same clone — so trust
in the source is trust in the fixed URL (HTTPS) the bundle is cloned from. The URL comes from the
environment or the user's own global config, never from a request.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess  # nosec B404 — fixed argv, no shell
from dataclasses import dataclass
from typing import Any

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

from core.config.paths import get_global_dir
from interface.ui.status import API_VERSION

DEFAULT_REPO = "https://github.com/ashlesh-t/cognirepo-console"
DEFAULT_REF = "release"
MANIFEST = "console.json"
CLONE_TIMEOUT_S = 120
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
# Transports git may use for the clone. Notably absent: ``ext::`` (runs a command).
_ALLOWED_PROTOCOLS = "https:file:ssh"


def console_dir() -> str:
    return os.path.join(get_global_dir(), "console")


@dataclass(frozen=True)
class Bundle:
    path: str
    version: str
    files: frozenset[str]


@dataclass(frozen=True)
class Outcome:
    """Result of ``ensure``. ``bundle`` is set when a verified console is available."""
    status: str  # ready | fetched | disabled | no-git | failed | invalid
    message: str
    bundle: Bundle | None = None


def _user_config() -> dict[str, Any]:
    """The ``ui`` section of ``<global>/config.json`` (optional, read-only)."""
    try:
        with open(os.path.join(get_global_dir(), "config.json"), encoding="utf-8") as f:
            ui = json.load(f).get("ui")
    except (OSError, ValueError, AttributeError):
        return {}
    return ui if isinstance(ui, dict) else {}


def settings() -> dict[str, Any]:
    """``repo``, ``ref`` and ``autofetch`` — environment wins over ``ui.*`` in the global config."""
    cfg = _user_config()
    env_fetch = os.environ.get("COGNIREPO_CONSOLE_AUTOFETCH")
    if env_fetch is not None:
        autofetch = env_fetch.strip().lower() not in ("0", "false", "no", "off")
    else:
        autofetch = cfg.get("console_autofetch", True) is not False
    return {
        "repo": str(os.environ.get("COGNIREPO_CONSOLE_REPO") or cfg.get("console_repo") or DEFAULT_REPO),
        "ref": str(os.environ.get("COGNIREPO_CONSOLE_REF") or cfg.get("console_ref") or DEFAULT_REF),
        "autofetch": autofetch,
    }


def validate(path: str) -> tuple[Bundle | None, str]:
    """Check an installed bundle. Returns ``(bundle, "")`` or ``(None, reason)``."""
    try:
        with open(os.path.join(path, MANIFEST), encoding="utf-8") as f:
            man = json.load(f)
    except OSError:
        return None, f"{MANIFEST} is missing"
    except ValueError:
        return None, f"{MANIFEST} is not valid JSON"
    if not isinstance(man, dict) or man.get("name") != "cognirepo-console":
        return None, f"{MANIFEST} is not a cognirepo-console manifest"
    if str(man.get("api_major")) != API_VERSION:
        return None, (f"console API major {man.get('api_major')!r} does not match this server's "
                      f"{API_VERSION!r}")
    files = man.get("files")
    if not isinstance(files, dict) or "index.html" not in files:
        return None, f"{MANIFEST} does not list index.html"
    root = os.path.realpath(path)
    for rel, digest in files.items():
        if not isinstance(rel, str) or not isinstance(digest, str) or not _SHA256.match(digest):
            return None, f"{MANIFEST} has a malformed file entry"
        parts = rel.split("/")
        if rel.startswith("/") or "\\" in rel or any(p in ("", ".", "..") for p in parts) or parts[0] == ".git":
            return None, f"{MANIFEST} lists an unsafe path: {rel!r}"
        full = os.path.join(root, *parts)
        if os.path.realpath(full) != full:  # a symlink somewhere on the way
            return None, f"{rel} is a symlink or escapes the console directory"
        try:
            with open(full, "rb") as f:
                actual = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            return None, f"{rel} is listed but missing"
        if not hmac.compare_digest(actual, digest):
            return None, f"{rel} does not match its sha256 in {MANIFEST}"
    return Bundle(path=root, version=str(man.get("version", "unknown")), files=frozenset(files)), ""


def resolve() -> tuple[Bundle | None, str]:
    """The installed, verified bundle (offline, read-only). ``(None, reason)`` if absent or invalid;
    an absent directory has an empty reason."""
    path = console_dir()
    if not os.path.isdir(path):
        return None, ""
    return validate(path)


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"  # never block on a credentials prompt
    env["GIT_ALLOW_PROTOCOL"] = _ALLOWED_PROTOCOLS
    return env


def _clone(repo: str, ref: str, dest: str) -> str:
    """Shallow-clone ``ref`` of ``repo`` into ``dest``. Returns "" or an error line."""
    if repo.startswith("-") or ref.startswith("-"):
        return "refusing a console repo/ref that starts with '-'"
    argv = ["git", "clone", "--depth", "1", "--branch", ref, "--single-branch", "--quiet", "--", repo, dest]
    try:
        proc = subprocess.run(  # nosec B603 — argv list, no shell, fixed or user-configured URL only
            argv, capture_output=True, text=True, timeout=CLONE_TIMEOUT_S, env=_git_env(), check=False)
    except subprocess.TimeoutExpired:
        return f"git clone timed out after {CLONE_TIMEOUT_S}s"
    except OSError as exc:
        return str(exc)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return tail[-1] if tail else f"git exited {proc.returncode}"
    return ""


def ensure(autofetch: bool | None = None) -> Outcome:
    """Make a verified console available, cloning it if missing. Called by ``cognirepo ui`` only."""
    bundle, reason = resolve()
    if bundle:
        return Outcome("ready", f"console {bundle.version}", bundle)
    if reason:  # present but unusable: never overwrite it silently (it may be a mid-edit checkout)
        return Outcome("invalid", f"installed console is unusable: {reason}")
    cfg = settings()
    if autofetch is None:
        autofetch = cfg["autofetch"]
    if not autofetch:
        return Outcome("disabled", "console auto-fetch is off")
    if shutil.which("git") is None:
        return Outcome("no-git", "git is not installed")

    dest = console_dir()
    staging = f"{dest}.tmp-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    err = _clone(cfg["repo"], cfg["ref"], staging)
    if err:
        shutil.rmtree(staging, ignore_errors=True)
        return Outcome("failed", f"could not fetch the console: {err}")
    bundle, reason = validate(staging)
    if bundle is None:
        shutil.rmtree(staging, ignore_errors=True)
        return Outcome("invalid", f"fetched console was refused: {reason}")
    try:
        os.rename(staging, dest)
    except OSError as exc:  # lost a race with another `cognirepo ui`, or a read-only home
        shutil.rmtree(staging, ignore_errors=True)
        bundle, reason = resolve()
        if bundle:
            return Outcome("ready", f"console {bundle.version}", bundle)
        return Outcome("failed", f"could not install the console: {exc}")
    bundle, reason = validate(dest)
    if bundle is None:
        return Outcome("invalid", f"fetched console was refused: {reason}")
    return Outcome("fetched", f"installed console {bundle.version}", bundle)


class ManifestStaticFiles(StaticFiles):
    """Serves only the files ``console.json`` lists — never ``.git/`` or anything else in the tree."""

    def __init__(self, bundle: Bundle) -> None:
        super().__init__(directory=bundle.path, html=True)
        self._allowed = bundle.files

    async def get_response(self, path: str, scope):  # type: ignore[override]
        rel = path.strip("/")  # Starlette passes "." for the root, which html=True maps to index.html
        if rel not in ("", ".") and rel not in self._allowed:
            raise HTTPException(status_code=404)
        return await super().get_response(path, scope)
