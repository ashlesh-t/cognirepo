# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
orchestrator/provider_status.py — which agent CLIs are installed, enabled and known to work (#87/#88).

CogniRepo's own router needs a backend to call. Besides API keys, a logged-in agent CLI (``claude``,
``codex``, ``gemini``) can serve as a headless completion backend. This module only *detects*: it never
runs a model, never touches the network and never spends quota.

Readiness is tri-state because "installed" is not "logged in":

* ``installed`` — the binary is on ``PATH`` and answers ``--version`` (milliseconds, local).
* ``ready``     — ``True`` after a successful real call, ``False`` after an auth failure, ``None`` (unknown)
                  when never called or when the CLI's version changed since it was last checked.

State lives in ``<global dir>/provider_status.json`` (0600, per user, because a CLI login is per user and
one login serves many repos). Reads never raise; writes are best-effort.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess  # nosec B404
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

STATUS_FILE = "provider_status.json"
_STATUS_VERSION = 1
VERSION_TIMEOUT_S = 3.0
_MAX_VERSION_LEN = 80


@dataclass(frozen=True)
class CliAgentSpec:
    """Static facts about one agent CLI. Flags for headless calls live in the adapter, not here."""

    name: str
    binary: str
    #: Vendor terms for driving this CLI's consumer login from a third-party tool are reported as
    #: restrictive; enabling it needs an explicit acknowledgement (see ``cognirepo agents enable``).
    terms_gated: bool = False


CLI_AGENT_SPECS: dict[str, CliAgentSpec] = {
    "claude": CliAgentSpec("claude", "claude", terms_gated=True),
    "codex": CliAgentSpec("codex", "codex"),
    "gemini": CliAgentSpec("gemini", "gemini", terms_gated=True),
}


@dataclass(frozen=True)
class ProviderStatus:
    """One backend as the router and ``cognirepo agents list`` see it."""

    name: str
    kind: str                      # "cli" (API-key providers join in a later change)
    installed: bool
    enabled: bool
    ready: bool | None             # None = unknown
    version: str | None
    path: str | None
    terms_gated: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def status_path() -> str:
    from core.config.paths import get_global_dir  # pylint: disable=import-outside-toplevel
    return os.path.join(get_global_dir(), STATUS_FILE)


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load() -> dict[str, Any]:
    """The whole status document, or an empty skeleton. Never raises, never writes."""
    import json  # pylint: disable=import-outside-toplevel
    try:
        with open(status_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {"version": _STATUS_VERSION, "cli": {}}
    if not isinstance(data, dict) or not isinstance(data.get("cli"), dict):
        return {"version": _STATUS_VERSION, "cli": {}}
    return data


def _save(doc: dict[str, Any]) -> bool:
    """Atomic, locked, 0600 write. Returns False instead of raising (status is advisory)."""
    from core.config.atomic import atomic_json_dump  # pylint: disable=import-outside-toplevel
    from core.config.lock import store_lock  # pylint: disable=import-outside-toplevel
    try:
        path = status_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with store_lock(timeout=2.0, lock_path=path + ".lock"):
            atomic_json_dump(path, doc, indent=2, fsync=False)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        return True
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("provider status not saved: %s", exc)
        return False


def record_readiness(name: str, ready: bool | None, version: str | None = None) -> bool:
    """Remember that ``name`` worked (``True``), was rejected (``False``) or must be re-probed (``None``)."""
    if name not in CLI_AGENT_SPECS:
        return False
    doc = load()
    doc["version"] = _STATUS_VERSION
    doc["cli"][name] = {"ready": ready, "version": version, "checked_at": _now()}
    return _save(doc)


def _probe_version(path: str, timeout: float) -> str | None:
    """First line of ``<binary> --version``, or None if it fails, hangs or prints nothing."""
    # absolute path from shutil.which, fixed argv, no shell
    try:
        proc = subprocess.run(  # nosec B603
            [path, "--version"], capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("%s --version failed: %s", path, exc)
        return None
    if proc.returncode != 0:
        return None
    for line in (proc.stdout or proc.stderr or "").splitlines():
        line = line.strip()
        if line:
            return line[:_MAX_VERSION_LEN]
    return None


def _enabled_agents() -> dict[str, bool]:
    """``cli_providers.<name>.enabled`` from the repo's config.json; empty outside an initialised repo."""
    import json  # pylint: disable=import-outside-toplevel
    try:
        from core.config.paths import get_path  # pylint: disable=import-outside-toplevel
        with open(get_path("config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception:  # pylint: disable=broad-except
        return {}
    block = cfg.get("cli_providers") if isinstance(cfg, dict) else None
    if not isinstance(block, dict):
        return {}
    return {n: bool(v.get("enabled")) for n, v in block.items() if isinstance(v, dict)}


def _detect_one(spec: CliAgentSpec, timeout: float) -> tuple[str | None, str | None]:
    path = shutil.which(spec.binary)
    if not path:
        return None, None
    return path, _probe_version(path, timeout)


def detect_cli_agents(timeout: float = VERSION_TIMEOUT_S) -> list[ProviderStatus]:
    """Detect every known agent CLI. Local only; bounded by ``timeout`` per binary, run in parallel."""
    specs = list(CLI_AGENT_SPECS.values())
    with ThreadPoolExecutor(max_workers=len(specs)) as pool:
        found = list(pool.map(lambda s: _detect_one(s, timeout), specs))
    saved = load()["cli"]
    enabled = _enabled_agents()
    rows: list[ProviderStatus] = []
    for spec, (path, version) in zip(specs, found):
        installed = path is not None and version is not None  # on PATH and answers --version
        prior = saved.get(spec.name) if isinstance(saved.get(spec.name), dict) else {}
        ready = prior.get("ready") if installed and prior.get("version") == version else None
        rows.append(ProviderStatus(
            name=spec.name, kind="cli", installed=installed, enabled=bool(enabled.get(spec.name)),
            ready=ready if isinstance(ready, bool) else None, version=version, path=path,
            terms_gated=spec.terms_gated,
        ))
    return rows
