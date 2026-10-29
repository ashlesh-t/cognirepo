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
from typing import Any, Callable

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
    if not isinstance(data.get("api"), dict):
        data.pop("api", None)
    return data


def modify(mutator: Callable[[dict[str, Any]], None]) -> bool:
    """Locked read-modify-write of the whole status document (the CLI and API sections share one file).

    ``mutator`` edits the loaded document in place. Atomic, 0600, returns False instead of raising: status is
    advisory and must never break the caller.
    """
    from core.config.atomic import atomic_json_dump  # pylint: disable=import-outside-toplevel
    from core.config.lock import store_lock  # pylint: disable=import-outside-toplevel
    try:
        path = status_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with store_lock(timeout=2.0, lock_path=path + ".lock"):
            doc = load()
            doc["version"] = _STATUS_VERSION
            mutator(doc)
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
    stamp = {"ready": ready, "version": version, "checked_at": _now()}
    return modify(lambda doc: doc["cli"].__setitem__(name, stamp))


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


def _read_config() -> dict[str, Any]:
    """This repo's config.json, or {} outside an initialised repo / when unreadable. Never raises."""
    import json  # pylint: disable=import-outside-toplevel
    try:
        from core.config.paths import get_path  # pylint: disable=import-outside-toplevel
        with open(get_path("config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception:  # pylint: disable=broad-except
        return {}
    return cfg if isinstance(cfg, dict) else {}


def cli_settings(cfg: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """``cli_providers`` from config.json: ``{agent: {"enabled": bool, "terms_ack": bool}}`` (known agents only)."""
    block = (cfg if cfg is not None else _read_config()).get("cli_providers")
    if not isinstance(block, dict):
        return {}
    return {n: v for n, v in block.items() if n in CLI_AGENT_SPECS and isinstance(v, dict)}


def _enabled_agents() -> dict[str, bool]:
    return {n: bool(v.get("enabled")) for n, v in cli_settings().items()}


def provider_preference(cfg: dict[str, Any] | None = None) -> str:
    """``"api"`` (default: API keys before CLIs) or ``"cli"``."""
    value = (cfg if cfg is not None else _read_config()).get("provider_preference")
    return "cli" if value == "cli" else "api"


def enabled_cli_backends(cfg: dict[str, Any] | None = None) -> list[str]:
    """Agent names the router may use right now, best first. Cheap enough for the hot path: no subprocess.

    An agent qualifies when it is enabled (and, if its vendor terms are reported restrictive, the user
    acknowledged that), its binary is on PATH, and its last recorded outcome was not an auth failure.
    Known-working agents come before untested ones.
    """
    settings = cli_settings(cfg)
    saved = load()["cli"]
    good: list[str] = []
    unknown: list[str] = []
    for name, spec in CLI_AGENT_SPECS.items():
        conf = settings.get(name)
        if not conf or not conf.get("enabled"):
            continue
        if spec.terms_gated and not conf.get("terms_ack"):
            continue
        if not shutil.which(spec.binary):
            continue
        prior = saved.get(name)
        ready = prior.get("ready") if isinstance(prior, dict) else None
        if ready is False:
            continue
        (good if ready is True else unknown).append(name)
    return good + unknown


def mark_result(agent: str, ok: bool) -> None:
    """Record that a real call to ``agent`` worked or was rejected. No write when nothing changed. Never raises."""
    try:
        spec = CLI_AGENT_SPECS.get(agent)
        if spec is None:
            return
        prior = load()["cli"].get(agent)
        if isinstance(prior, dict) and prior.get("ready") is ok:
            return
        path = shutil.which(spec.binary)
        record_readiness(agent, ok, _probe_version(path, VERSION_TIMEOUT_S) if path else None)
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("mark_result(%s) skipped: %s", agent, exc)


TERMS_WARNING = (
    "Vendor terms for driving a consumer subscription login from a third-party tool are reported to be "
    "restrictive for this CLI (accounts have reportedly been limited or suspended). Re-run with "
    "--accept-terms-risk to enable it anyway, at your own risk. An API key avoids the question."
)
DATA_NOTICE = (
    "Enabled CLIs receive repo-derived context from your queries and use your own subscription quota. "
    "They run with tools, MCP and hooks off. Verify with: cognirepo agents probe {name}"
)


def _write_setting(agent: str, value: dict[str, Any]) -> None:
    from core.config.paths import get_cognirepo_dir  # pylint: disable=import-outside-toplevel
    from core.config.store_settings import set_value  # pylint: disable=import-outside-toplevel
    set_value(get_cognirepo_dir(), "cli_providers", agent, value)


def enable_agent(agent: str, accept_terms_risk: bool = False) -> tuple[bool, str]:
    """Turn ``agent`` on as a routing backend. Returns ``(ok, message)``; writes nothing on refusal."""
    from core.config.store_settings import SettingsError  # pylint: disable=import-outside-toplevel
    spec = CLI_AGENT_SPECS.get(agent)
    if spec is None:
        return False, f"unknown agent {agent!r} (known: {', '.join(CLI_AGENT_SPECS)})"
    if not shutil.which(spec.binary):
        return False, f"{spec.binary} was not found on PATH"
    prior = cli_settings().get(agent, {})
    acked = bool(accept_terms_risk or prior.get("terms_ack"))
    if spec.terms_gated and not acked:
        return False, TERMS_WARNING
    try:
        _write_setting(agent, {"enabled": True, "terms_ack": acked})
    except SettingsError as exc:
        return False, exc.message
    return True, f"{agent} enabled. " + DATA_NOTICE.format(name=agent)


def apply_choices(choices: dict[str, bool]) -> list[tuple[str, bool, str]]:
    """Enable what the setup wizard collected (``{agent: terms_risk_accepted}``). Returns ``(agent, ok, message)``."""
    return [(name, *enable_agent(name, accept_terms_risk=bool(acked))) for name, acked in choices.items()]


def disable_agent(agent: str) -> tuple[bool, str]:
    from core.config.store_settings import SettingsError  # pylint: disable=import-outside-toplevel
    if agent not in CLI_AGENT_SPECS:
        return False, f"unknown agent {agent!r} (known: {', '.join(CLI_AGENT_SPECS)})"
    prior = cli_settings().get(agent, {})
    try:
        _write_setting(agent, {"enabled": False, "terms_ack": bool(prior.get("terms_ack"))})
    except SettingsError as exc:
        return False, exc.message
    return True, f"{agent} disabled."


def probe_agent(agent: str, timeout: float = 60.0) -> tuple[bool | None, str]:
    """One tiny real call to an *enabled* agent. Records readiness. Returns ``(ready, detail)``.

    ``ready`` is None when the outcome says nothing about login (timeout, crash)."""
    from intelligence.orchestrator.model_adapters import cli_adapter  # pylint: disable=import-outside-toplevel
    from intelligence.orchestrator.model_adapters.errors import ModelCallError  # pylint: disable=import-outside-toplevel
    spec = CLI_AGENT_SPECS.get(agent)
    if spec is None:
        return None, f"unknown agent {agent!r}"
    conf = cli_settings().get(agent, {})
    if not conf.get("enabled"):
        return None, f"{agent} is not enabled (cognirepo agents enable {agent})"
    if spec.terms_gated and not conf.get("terms_ack"):
        return None, TERMS_WARNING
    path = shutil.which(spec.binary)
    version = _probe_version(path, VERSION_TIMEOUT_S) if path else None
    try:
        reply = cli_adapter.call("Reply with the single word OK.", agent=agent, timeout=timeout)
    except ModelCallError as exc:
        if exc.status_code == 401:
            record_readiness(agent, False, version)
            return False, f"not logged in or rejected: {exc.message}"
        return None, f"inconclusive: {exc.message}"
    record_readiness(agent, True, version)
    return True, f"ok ({reply.usage.get('input_tokens', 0)} in / {reply.usage.get('output_tokens', 0)} out tokens)"


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
