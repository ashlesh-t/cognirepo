# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
API-key verification probes — one function per provider.

Each function makes the minimal possible API call to verify the key is valid.
Returns a dict:
    {ok: bool, latency_ms: float, error: str}
"""
from __future__ import annotations

import time
from typing import TypedDict


def _anthropic_default_model() -> str:
    try:
        from orchestrator.classifier import DEFAULT_MODELS_BY_PROVIDER  # pylint: disable=import-outside-toplevel
        return DEFAULT_MODELS_BY_PROVIDER.get("anthropic", "claude-haiku-4-5")
    except ImportError:
        return "claude-haiku-4-5"


class ProbeResult(TypedDict):
    ok: bool
    latency_ms: float
    error: str


def _elapsed_ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)


def probe_anthropic(api_key: str, timeout: float = 10.0) -> ProbeResult:
    """POST /v1/messages with max_tokens=1 to verify the key."""
    import urllib.request  # pylint: disable=import-outside-toplevel
    import urllib.error    # pylint: disable=import-outside-toplevel
    import json            # pylint: disable=import-outside-toplevel

    t0 = time.perf_counter()
    payload = json.dumps({
        "model": _anthropic_default_model(),
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "ping"}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            resp.read()
            return {"ok": True, "latency_ms": _elapsed_ms(t0), "error": ""}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "latency_ms": _elapsed_ms(t0), "error": f"HTTP {exc.code} {exc.reason}"}
    except Exception as exc:  # pylint: disable=broad-except
        return {"ok": False, "latency_ms": _elapsed_ms(t0), "error": str(exc)}


def probe_gemini(api_key: str, timeout: float = 10.0) -> ProbeResult:
    """GET generativelanguage.googleapis.com/v1/models to verify the key."""
    import urllib.request  # pylint: disable=import-outside-toplevel
    import urllib.error    # pylint: disable=import-outside-toplevel

    t0 = time.perf_counter()
    url = f"https://generativelanguage.googleapis.com/v1/models?key={api_key}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # nosec B310
            resp.read()
            return {"ok": True, "latency_ms": _elapsed_ms(t0), "error": ""}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "latency_ms": _elapsed_ms(t0), "error": f"HTTP {exc.code} {exc.reason}"}
    except Exception as exc:  # pylint: disable=broad-except
        return {"ok": False, "latency_ms": _elapsed_ms(t0), "error": str(exc)}


def probe_openai(api_key: str, timeout: float = 10.0) -> ProbeResult:
    """GET api.openai.com/v1/models to verify the key."""
    import urllib.request  # pylint: disable=import-outside-toplevel
    import urllib.error    # pylint: disable=import-outside-toplevel

    t0 = time.perf_counter()
    req = urllib.request.Request(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            resp.read()
            return {"ok": True, "latency_ms": _elapsed_ms(t0), "error": ""}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "latency_ms": _elapsed_ms(t0), "error": f"HTTP {exc.code} {exc.reason}"}
    except Exception as exc:  # pylint: disable=broad-except
        return {"ok": False, "latency_ms": _elapsed_ms(t0), "error": str(exc)}


def probe_grok(api_key: str, timeout: float = 10.0) -> ProbeResult:
    """GET api.x.ai/v1/models to verify the key."""
    import urllib.request  # pylint: disable=import-outside-toplevel
    import urllib.error    # pylint: disable=import-outside-toplevel

    t0 = time.perf_counter()
    req = urllib.request.Request(
        "https://api.x.ai/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            resp.read()
            return {"ok": True, "latency_ms": _elapsed_ms(t0), "error": ""}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "latency_ms": _elapsed_ms(t0), "error": f"HTTP {exc.code} {exc.reason}"}
    except Exception as exc:  # pylint: disable=broad-except
        return {"ok": False, "latency_ms": _elapsed_ms(t0), "error": str(exc)}


# ── registry ──────────────────────────────────────────────────────────────────

PROVIDER_PROBES: dict[str, tuple[str, object]] = {
    "ANTHROPIC_API_KEY": ("anthropic", probe_anthropic),
    "GEMINI_API_KEY":    ("gemini",    probe_gemini),
    "OPENAI_API_KEY":    ("openai",    probe_openai),
    "GROK_API_KEY":      ("grok",      probe_grok),
}
