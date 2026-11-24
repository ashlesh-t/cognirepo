# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
orchestrator/gateway.py — settings for an OpenAI-compatible gateway: one URL and one key in front of many models
(LiteLLM, OpenRouter, aicredits.in, a local proxy, ...).

Where each setting comes from (the environment wins over the user-level file):

=============  ==============================  ===================================================
setting        environment                     ``<global dir>/config.json`` -> ``"gateway"``
=============  ==============================  ===================================================
base URL       ``COGNIREPO_GATEWAY_BASE_URL``  ``base_url``
key            ``COGNIREPO_GATEWAY_API_KEY``   (never read from a file)
preferred id   ``COGNIREPO_GATEWAY_PREFER``    ``prefer``
=============  ==============================  ===================================================

Security. The URL decides where the key is sent, so it is **never** read from a repo's ``.cognirepo/config.json``: a
cloned repo could ship one and redirect the user's key to its author's server. The URL must be ``https://`` (plain
``http://`` only for loopback, for a local proxy) and carry no credentials, query or fragment. The full URL is never
logged, printed or cached (some gateways put a token in the path); only the host is shown.

Every function here is total: a missing, unreadable or invalid setting reads as "not configured".
"""
from __future__ import annotations

import json
import logging
import os
import re
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

ENV_URL = "COGNIREPO_GATEWAY_BASE_URL"
ENV_KEY = "COGNIREPO_GATEWAY_API_KEY"
ENV_PREFER = "COGNIREPO_GATEWAY_PREFER"

_MAX_URL = 300
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
_PREFER_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,64}$")
_BAD_CHARS_RE = re.compile(r"[\s\x00-\x1f\x7f?#]")
_warned: set[str] = set()


def _once(message: str) -> None:
    """Log a configuration problem once per process (never the value itself)."""
    if message not in _warned:
        _warned.add(message)
        logger.warning(message)


def _global_section() -> dict:
    """The ``gateway`` object of the user-level config, or ``{}``."""
    try:
        from core.config.paths import get_global_dir  # pylint: disable=import-outside-toplevel
        with open(os.path.join(get_global_dir(), "config.json"), encoding="utf-8") as fh:
            section = json.load(fh).get("gateway")
        return section if isinstance(section, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def normalize_url(raw: object) -> str | None:
    """``raw`` without a trailing slash if it is an acceptable gateway URL, else None.

    Acceptable: ``https://host[:port][/path]``, or ``http://`` to ``127.0.0.1`` / ``localhost`` / ``::1``; no user
    info, query, fragment, whitespace or control characters; at most 300 characters.
    """
    if not isinstance(raw, str):
        return None
    url = raw.strip()
    if not url or len(url) > _MAX_URL or _BAD_CHARS_RE.search(url):
        return None
    try:
        parts = urlsplit(url)
        hostname = parts.hostname
        _ = parts.port  # raises ValueError on a malformed or out-of-range port
    except ValueError:
        return None
    if not hostname or parts.username is not None or parts.password is not None:
        return None
    if parts.scheme == "https":
        return url.rstrip("/")
    if parts.scheme == "http" and hostname.lower() in _LOOPBACK:
        return url.rstrip("/")
    return None


def is_loopback_http(url: object) -> bool:
    """True for an ``http://`` URL that :func:`normalize_url` accepts, i.e. one that points at this machine."""
    return isinstance(url, str) and url.startswith("http://") and normalize_url(url) is not None


def base_url() -> str | None:
    """The validated gateway base URL (no trailing slash), or None when unset or invalid."""
    raw = os.environ.get(ENV_URL) or _global_section().get("base_url")
    if not raw:
        return None
    url = normalize_url(raw)
    if url is None:
        _once("gateway base URL ignored: it must be https:// (or http:// to localhost) with no credentials, "
              "query or fragment")
    return url


def api_key() -> str | None:
    """The gateway key. Environment only: a key is never read from, or written to, a file."""
    return os.environ.get(ENV_KEY) or None


def prefer() -> str | None:
    """Lower-cased id prefix the automatic model pick is limited to (e.g. ``anthropic/``), or None."""
    raw = os.environ.get(ENV_PREFER) or _global_section().get("prefer")
    if not raw:
        return None
    if isinstance(raw, str) and _PREFER_RE.match(raw.strip()):
        return raw.strip().lower()
    _once("gateway 'prefer' ignored: use up to 64 characters from [A-Za-z0-9._:/-]")
    return None


def configured() -> bool:
    """A usable gateway: a valid URL and a key."""
    return bool(api_key() and base_url())


def host() -> str | None:
    """``host[:port]`` of the gateway, for display. Never the path (it may hold a token)."""
    url = base_url()
    return urlsplit(url).netloc if url else None
