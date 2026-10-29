# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
orchestrator/model_discovery.py — ask each provider which models an API key can use (#87/#88, phase 2).

Opt-in and on demand: ``cognirepo models refresh`` is the only thing that touches the network. The router never
fetches; it only *reads* the cache this module writes, through ``classifier.resolve_model``, to replace a retired
default or prefer a newer model of the same family and tier. With no cache the router behaves exactly as before.

Cache: the ``api`` section of ``~/.cognirepo/provider_status.json`` (0600, per user, because a key is per user).
Per provider: ``fetched_at``, ``key_fingerprint`` (sha256 prefix, never the key), ``rules_hash`` (a cache written
under other tier rules is stale), ``models`` and ``denied``. TTL 24 h; stale entries are ignored, not deleted.

No model-ID literals live here: tier rules, parsing helpers and the resolve ladder are in ``classifier.py``.
Model names come from the provider's own response and are validated before use.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from intelligence.orchestrator import provider_status
from intelligence.orchestrator.classifier import (
    MODEL_ID_RE, assign_tier, hardcoded_models, is_dated_snapshot, is_prerelease, model_family, model_version, rules_hash,
)

logger = logging.getLogger(__name__)

TTL_SECONDS = 24 * 3600
REQUEST_TIMEOUT_S = 5.0
TOTAL_TIMEOUT_S = 8.0
_MAX_PAGES = 5
_MAX_BODY = 5_000_000
PROVIDERS = ("anthropic", "openai", "gemini", "grok")
_TIERS = ("STANDARD", "COMPLEX", "EXPERT")

_KEY_ENV: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "grok": ("GROK_API_KEY",),
}


@dataclass(frozen=True)
class ModelInfo:
    """One model as a provider reported it."""

    id: str
    created: str | None = None
    ctx: int | None = None
    methods: tuple[str, ...] | None = None


class FetchError(Exception):
    """A provider list call failed. ``kind`` is one of: rejected (401/403), transient (429/5xx/network), malformed."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


# ── keys ─────────────────────────────────────────────────────────────────────────────────────────

def api_key(provider: str) -> str | None:
    for var in _KEY_ENV.get(provider, ()):
        value = os.environ.get(var)
        if value:
            return value
    return None


def fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:12]


# ── HTTP ─────────────────────────────────────────────────────────────────────────────────────────

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _get_json(url: str, headers: dict[str, str], timeout: float) -> Any:
    """GET ``url`` and decode JSON. Raises FetchError. Keys travel in headers only, never in the URL."""
    if not url.startswith("https://"):
        raise FetchError("malformed", "refusing a non-https URL")
    req = urllib.request.Request(url, headers={**headers, "accept": "application/json"}, method="GET")
    try:
        # no redirects: a 3xx would forward the key header to wherever it points (possibly plain http)
        with _OPENER.open(req, timeout=timeout) as resp:  # nosec B310 - https only, fixed provider hosts
            body = resp.read(_MAX_BODY)
    except urllib.error.HTTPError as exc:
        kind = "rejected" if exc.code in (401, 403) else "transient"
        raise FetchError(kind, f"HTTP {exc.code}") from exc
    except Exception as exc:  # pylint: disable=broad-except
        raise FetchError("transient", type(exc).__name__) from exc
    try:
        return json.loads(body)
    except ValueError as exc:
        raise FetchError("malformed", "response is not JSON") from exc


def _valid(model_id: Any) -> bool:
    return isinstance(model_id, str) and bool(MODEL_ID_RE.match(model_id))


def _int(value: Any) -> int | None:
    try:
        n = int(value)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


# ── per-provider fetch + parse (pure parse functions are tested with canned bodies) ───────────────

def parse_anthropic(page: Any) -> tuple[list[ModelInfo], str | None]:
    rows = page.get("data") if isinstance(page, dict) else None
    if not isinstance(rows, list):
        raise FetchError("malformed", "no data list")
    out = [ModelInfo(id=r["id"], created=r.get("created_at"), ctx=_int(r.get("max_input_tokens")))
           for r in rows if isinstance(r, dict) and _valid(r.get("id"))]
    more = page.get("last_id") if page.get("has_more") and _valid(page.get("last_id")) else None
    return out, more


def parse_openai(page: Any) -> tuple[list[ModelInfo], str | None]:
    rows = page.get("data") if isinstance(page, dict) else None
    if not isinstance(rows, list):
        raise FetchError("malformed", "no data list")
    return [ModelInfo(id=r["id"], created=str(r["created"]) if r.get("created") else None)
            for r in rows if isinstance(r, dict) and _valid(r.get("id"))], None


def parse_gemini(page: Any) -> tuple[list[ModelInfo], str | None]:
    rows = page.get("models") if isinstance(page, dict) else None
    if not isinstance(rows, list):
        raise FetchError("malformed", "no models list")
    out = []
    for r in rows:
        if not isinstance(r, dict) or not isinstance(r.get("name"), str):
            continue
        mid = r["name"].split("/", 1)[-1]
        methods = r.get("supportedGenerationMethods")
        if _valid(mid):
            out.append(ModelInfo(id=mid, ctx=_int(r.get("inputTokenLimit")),
                                 methods=tuple(methods) if isinstance(methods, list) else None))
    token = page.get("nextPageToken")
    return out, token if isinstance(token, str) and token else None


def parse_grok(page: Any) -> tuple[list[ModelInfo], str | None]:
    rows = (page.get("models") or page.get("data")) if isinstance(page, dict) else None
    if not isinstance(rows, list):
        raise FetchError("malformed", "no model list")
    return [ModelInfo(id=r["id"], created=str(r["created"]) if r.get("created") else None)
            for r in rows if isinstance(r, dict) and _valid(r.get("id"))], None


def _fetch_paged(key: str, timeout: float, provider: str,
                 deadline: float | None = None) -> tuple[list[ModelInfo], str]:
    def get(url: str, headers: dict[str, str]) -> Any:
        """One request, never allowed to outlive the shared deadline (so a worker thread cannot hang the exit)."""
        left = timeout if deadline is None else min(timeout, deadline - time.monotonic())
        if left <= 0:
            raise FetchError("transient", "deadline exceeded")
        return _get_json(url, headers, left)

    models: list[ModelInfo] = []
    cursor: str | None = None
    if provider == "anthropic":
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        for _ in range(_MAX_PAGES):
            url = "https://api.anthropic.com/v1/models?limit=100" + (
                f"&after_id={urllib.parse.quote(cursor)}" if cursor else "")
            page, cursor = parse_anthropic(get(url, headers))
            models += page
            if not cursor:
                break
        return models, "v1/models"
    if provider == "gemini":
        headers = {"x-goog-api-key": key}
        for _ in range(_MAX_PAGES):
            url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=100" + (
                f"&pageToken={urllib.parse.quote(cursor)}" if cursor else "")
            page, cursor = parse_gemini(get(url, headers))
            models += page
            if not cursor:
                break
        return models, "v1beta/models"
    headers = {"Authorization": f"Bearer {key}"}
    if provider == "grok":
        try:  # richer endpoint first, fall back to the OpenAI-compatible list
            return parse_grok(get("https://api.x.ai/v1/language-models", headers))[0], "v1/language-models"
        except FetchError as exc:
            if exc.kind == "rejected":
                raise
        return parse_grok(get("https://api.x.ai/v1/models", headers))[0], "v1/models"
    return parse_openai(get("https://api.openai.com/v1/models", headers))[0], "v1/models"


def fetch_provider_models(provider: str, key: str, timeout: float = REQUEST_TIMEOUT_S,
                          deadline: float | None = None) -> tuple[list[ModelInfo], str]:
    """All models ``key`` can list for ``provider`` plus the endpoint used. Raises FetchError."""
    models, endpoint = _fetch_paged(key, timeout, provider, deadline)
    if not models:
        raise FetchError("malformed", "provider returned no models")
    return models, endpoint


# ── tiering + cache ──────────────────────────────────────────────────────────────────────────────

def tier_models(models: list[ModelInfo], tier_overrides: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Cache rows ``{id, tier, ctx, created}``; ``tier`` is None for anything not routable or of unknown family."""
    overrides = tier_overrides or {}
    ids = frozenset(m.id for m in models)
    rows = []
    for m in sorted(models, key=lambda x: x.id):
        tier = overrides.get(m.id) or assign_tier(m.id, m.ctx, list(m.methods) if m.methods is not None else None)
        if tier is not None and is_dated_snapshot(m.id, ids):
            tier = None  # the undated alias is listed: prefer it
        rows.append({"id": m.id, "tier": tier, "ctx": m.ctx, "created": m.created})
    return rows


def _clean_tier_overrides(raw: Any) -> dict[str, str]:
    """Only ``{valid model id: STANDARD|COMPLEX|EXPERT}`` pairs; anything else is dropped (and logged once)."""
    if not isinstance(raw, dict):
        if raw:
            logger.warning("model_overrides.tiers must be an object; ignoring it")
        return {}
    good = {k: v for k, v in raw.items() if _valid(k) and v in _TIERS}
    if len(good) != len(raw):
        logger.warning("model_overrides.tiers: ignoring %d invalid entr%s", len(raw) - len(good),
                     "y" if len(raw) - len(good) == 1 else "ies")
    return good


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _age(iso: Any) -> float | None:
    try:
        then = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return (datetime.now(tz=timezone.utc) - then).total_seconds()
    except (TypeError, ValueError):
        return None


def load_entry(provider: str) -> dict[str, Any] | None:
    entry = (provider_status.load().get("api") or {}).get(provider)
    return entry if isinstance(entry, dict) and isinstance(entry.get("models"), list) else None


def entry_is_fresh(provider: str, entry: dict[str, Any], key: str | None = None) -> bool:
    """Fresh = within TTL, written under today's tier rules, and (when a key is set) for that same key."""
    age = _age(entry.get("fetched_at"))
    if age is None or age < 0 or age > TTL_SECONDS or entry.get("rules_hash") != rules_hash():
        return False
    key = key if key is not None else api_key(provider)
    return key is not None and entry.get("key_fingerprint") == fingerprint(key)


def clear_cache(provider: str | None = None) -> bool:
    def drop(doc: dict[str, Any]) -> None:
        api = doc.get("api")
        if not isinstance(api, dict):
            return
        if provider is None:
            doc.pop("api", None)
        else:
            api.pop(provider, None)
    return provider_status.modify(drop)


def deny(provider: str, model_id: str) -> None:
    """A real call found ``model_id`` missing for this key: stop picking it until the next refresh. Never a default."""
    if not _valid(model_id) or model_id in hardcoded_models():
        return

    def add(doc: dict[str, Any]) -> None:
        entry = (doc.get("api") or {}).get(provider)
        if isinstance(entry, dict) and model_id not in entry.setdefault("denied", []):
            entry["denied"].append(model_id)
    provider_status.modify(add)


def refresh(providers: list[str] | None = None, timeout: float = REQUEST_TIMEOUT_S,
            total_timeout: float = TOTAL_TIMEOUT_S, tier_overrides: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Fetch, tier and cache every provider that has a key. Never raises. Report per provider:
    ``{"status": ok|no_key|rejected|failed, "count": n, "detail": str}``. A failure keeps the previous cache."""
    wanted = [p for p in (providers or PROVIDERS) if p in PROVIDERS]
    report: dict[str, dict[str, Any]] = {}
    jobs: dict[str, tuple[str, Any]] = {}
    pool = ThreadPoolExecutor(max_workers=4)
    deadline = time.monotonic() + total_timeout
    try:
        for p in wanted:
            key = api_key(p)
            if key is None:
                report[p] = {"status": "no_key", "count": 0, "detail": "no API key set"}
            else:
                jobs[p] = (key, pool.submit(fetch_provider_models, p, key, timeout, deadline))
        for p, (key, fut) in jobs.items():
            try:
                models, endpoint = fut.result(timeout=max(0.0, deadline - time.monotonic()))
            except FetchError as exc:
                report[p] = {"status": "rejected" if exc.kind == "rejected" else "failed", "count": 0,
                             "detail": "key rejected" if exc.kind == "rejected" else exc.message}
                continue
            except Exception as exc:  # pylint: disable=broad-except
                report[p] = {"status": "failed", "count": 0, "detail": type(exc).__name__}
                continue
            try:
                rows = tier_models(models, _clean_tier_overrides(tier_overrides))
            except Exception as exc:  # pylint: disable=broad-except
                report[p] = {"status": "failed", "count": 0, "detail": type(exc).__name__}
                continue
            entry = {"fetched_at": _now(), "key_fingerprint": fingerprint(key), "endpoint": endpoint,
                     "rules_hash": rules_hash(), "models": rows, "denied": []}
            if provider_status.modify(lambda doc, p=p, entry=entry: doc.setdefault("api", {}).__setitem__(p, entry)):
                report[p] = {"status": "ok", "count": len(rows), "detail": endpoint}
            else:
                report[p] = {"status": "failed", "count": 0, "detail": "cache not writable"}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return report


# ── reading the cache (router hot path: one small JSON read, no network) ───────────────────────────

def pick_for_tier(provider: str, tier: str, baseline: str, overrides: dict[str, Any] | None = None) -> str | None:
    """A better model than ``baseline`` for ``tier`` from a fresh cache, or None to keep ``baseline``.

    * baseline listed: only a newer model of the same family and tier replaces it;
    * baseline missing (retired, or denied): the newest model assigned to ``tier``;
    * no fresh cache / nothing suitable: None.
    """
    entry = load_entry(provider)
    if entry is None or not entry_is_fresh(provider, entry):
        return None
    overrides = overrides or {}
    forced = {k: v for k, v in (overrides.get("tiers") or {}).items()
              if _valid(k) and v in ("STANDARD", "COMPLEX", "EXPERT")}
    blocked = set(entry.get("denied") or []) | {m for m in (overrides.get("deny") or []) if _valid(m)}
    rows = [r for r in entry["models"] if isinstance(r, dict) and _valid(r.get("id"))]
    listed = {r["id"] for r in rows}
    usable = [(r["id"], forced.get(r["id"]) or r.get("tier")) for r in rows if r["id"] not in blocked]
    usable = [(i, t) for i, t in usable if t]

    def newest(candidates: list[str]) -> str | None:
        return max(candidates, key=lambda i: (not is_prerelease(i), model_version(i), i), default=None)

    # A shipped alias ('claude-haiku-4-5') may be listed only as dated snapshots ('claude-haiku-4-5-2025...'):
    # that still means it exists, so it is not "retired".
    present = baseline if baseline in listed else next(
        (i for i in sorted(listed) if baseline and i.startswith(baseline + "-")
         and re.fullmatch(r"\d{8}|\d{4}-\d{2}-\d{2}", i[len(baseline) + 1:])), None)
    if baseline and present and baseline not in blocked:
        base_tier = next((t for i, t in usable if i in (baseline, present)), None)
        family = model_family(baseline)
        better = [i for i, t in usable if t == base_tier and base_tier and model_family(i) == family
                  and model_version(i) > model_version(baseline)]
        return newest(better)
    return newest([i for i, t in usable if t == tier])
