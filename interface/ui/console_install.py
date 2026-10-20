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


def _listed_files(path: str) -> frozenset[str] | None:
    """File list of an installed manifest, or None if it is unreadable or for another API major.
    No hashing: the bundle was verified when it was installed or updated."""
    try:
        with open(os.path.join(path, MANIFEST), encoding="utf-8") as f:
            man = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(man, dict) or str(man.get("api_major")) != API_VERSION or not isinstance(man.get("files"), dict):
        return None
    return frozenset(k for k in man["files"] if isinstance(k, str))


class ManifestStaticFiles(StaticFiles):
    """Serves only the files ``console.json`` lists — never ``.git/`` or anything else in the tree.

    The list is re-read when ``console.json`` changes, so ``cognirepo ui --update`` / ``--rollback`` take
    effect on a running server without a restart."""

    def __init__(self, bundle: Bundle) -> None:
        super().__init__(directory=bundle.path, html=True)
        self._path = bundle.path
        self._allowed: frozenset[str] | None = bundle.files
        self._stamp = self._stat()

    def _stat(self) -> tuple[int, int] | None:
        try:
            st = os.stat(os.path.join(self._path, MANIFEST))
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    async def get_response(self, path: str, scope):  # type: ignore[override]
        stamp = self._stat()
        if stamp != self._stamp:
            self._stamp = stamp
            self._allowed = _listed_files(self._path)
        rel = path.strip("/")  # Starlette passes "." for the root, which html=True maps to index.html
        if self._allowed is None or (rel not in ("", ".") and rel not in self._allowed):
            raise HTTPException(status_code=404)
        return await super().get_response(path, scope)


# --- update / rollback (#216) ----------------------------------------------------------------------


@dataclass(frozen=True)
class UpdateOutcome:
    # current | updated | available | incompatible | not-managed | failed | rolled-back | no-previous
    status: str
    message: str
    old: str | None = None
    new: str | None = None


def prev_dir() -> str:
    return console_dir() + ".prev"


def _git(cwd: str, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(  # nosec B603 — argv list, no shell; only fetch/rev-parse/show/reset run here
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=CLONE_TIMEOUT_S,
            env=_git_env(), check=False)
    except subprocess.TimeoutExpired:
        return 124, f"git {args[0]} timed out after {CLONE_TIMEOUT_S}s"
    except OSError as exc:
        return 127, str(exc)
    out = (proc.stdout if proc.returncode == 0 else (proc.stderr or proc.stdout)).strip()
    return proc.returncode, out.splitlines()[-1] if proc.returncode != 0 and out else out


def _fetched_manifest(staging: str) -> dict | None:
    code, text = _git(staging, "show", f"FETCH_HEAD:{MANIFEST}")
    if code != 0:
        return None
    try:
        man = json.loads(text)
    except ValueError:
        return None
    return man if isinstance(man, dict) else None


def _incompatible(man: dict) -> str:
    from core.config.version import __version__  # pylint: disable=import-outside-toplevel
    return (f"console {man.get('version', 'unknown')} was built for API major {man.get('api_major')!r}, but "
            f"cognirepo {__version__} serves API major {API_VERSION!r}. Refusing the update; "
            f"a console for that API major needs a cognirepo release that serves it.")


def _swap(staged: str, dest: str, prev: str) -> None:
    """dest -> prev, staged -> dest, via renames. A request landing between the two renames sees a 404."""
    shutil.rmtree(prev, ignore_errors=True)
    os.rename(dest, prev)
    try:
        os.rename(staged, dest)
    except OSError:
        os.rename(prev, dest)
        raise


def update(check_only: bool = False) -> UpdateOutcome:
    """Fetch the latest console build into a staged copy, verify it, and swap it in (keeping the
    previous build in ``console.prev/``). With ``check_only`` nothing in ``<global>/console/`` changes."""
    dest = console_dir()
    if not os.path.isdir(os.path.join(dest, ".git")):
        return UpdateOutcome("not-managed", "the console is not a git-managed install under "
                             f"{dest}; run `cognirepo ui` once to install it")
    if shutil.which("git") is None:
        return UpdateOutcome("failed", "git is not installed")
    ref = settings()["ref"]
    if ref.startswith("-"):
        return UpdateOutcome("failed", "refusing a console ref that starts with '-'")
    old, _ = validate(dest)
    old_v = old.version if old else None

    staging = f"{dest}.new-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    try:  # every git write below happens in this copy; the live build is never touched until the swap
        shutil.copytree(dest, staging, symlinks=True)
        code, msg = _git(staging, "fetch", "--depth", "1", "--quiet", "origin", ref)
        if code != 0:
            return UpdateOutcome("failed", f"could not fetch the console update: {msg}", old_v)
        man = _fetched_manifest(staging)
        if man is None:
            return UpdateOutcome("failed", f"the fetched build has no readable {MANIFEST}", old_v)
        new_v = str(man.get("version", "unknown"))
        if str(man.get("api_major")) != API_VERSION:
            return UpdateOutcome("incompatible", _incompatible(man), old_v, new_v)
        _, head = _git(staging, "rev-parse", "HEAD")
        _, fetched = _git(staging, "rev-parse", "FETCH_HEAD")
        if old is not None and head == fetched:
            return UpdateOutcome("current", f"console {old_v} is already current", old_v, new_v)
        if check_only:
            return UpdateOutcome("available", f"console update available: {old_v or 'unusable'} -> {new_v}",
                                 old_v, new_v)
        # A depth-1 fetch has no history, so a fast-forward merge is impossible (git refuses it as
        # "unrelated histories"), and the release branch is rebuilt by CI anyway. The staged tree is
        # instead checked out exactly as fetched; trust comes from validating it below, not from history.
        code, msg = _git(staging, "reset", "--hard", "--quiet", "FETCH_HEAD")
        if code != 0:
            return UpdateOutcome("failed", f"could not check out the fetched build: {msg}", old_v)
        bundle, reason = validate(staging)
        if bundle is None:
            return UpdateOutcome("failed", f"fetched console was refused: {reason}", old_v, new_v)
        try:
            _swap(staging, dest, prev_dir())
        except OSError as exc:
            return UpdateOutcome("failed", f"could not swap in the new console: {exc}", old_v, new_v)
        staging = ""  # moved into place
        return UpdateOutcome("updated", f"console updated: {old_v or 'unusable'} -> {new_v}", old_v, new_v)
    except OSError as exc:
        return UpdateOutcome("failed", f"could not stage the console update: {exc}", old_v)
    finally:
        if staging:
            shutil.rmtree(staging, ignore_errors=True)


def rollback() -> UpdateOutcome:
    """Swap ``console.prev/`` back in. The build being replaced becomes the new ``console.prev/``,
    so running it twice toggles between the two."""
    dest, prev = console_dir(), prev_dir()
    if not os.path.isdir(prev):
        return UpdateOutcome("no-previous", "there is no previous console build to roll back to")
    bundle, reason = validate(prev)
    if bundle is None:
        return UpdateOutcome("failed", f"the previous console build is unusable: {reason}")
    cur, _ = validate(dest)
    spare = f"{dest}.rollback-{os.getpid()}"
    try:
        shutil.rmtree(spare, ignore_errors=True)
        if os.path.isdir(dest):
            os.rename(dest, spare)
        os.rename(prev, dest)
        if os.path.isdir(spare):
            os.rename(spare, prev)
    except OSError as exc:
        return UpdateOutcome("failed", f"rollback failed: {exc}")
    return UpdateOutcome("rolled-back", f"console rolled back: {cur.version if cur else 'unusable'} -> "
                         f"{bundle.version}", cur.version if cur else None, bundle.version)
