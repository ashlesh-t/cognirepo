# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Security primitives for the local control API (framework-agnostic, unit-testable).

Threat model: a loopback-only server that a *browser* can reach, so any web page the user
visits can try to talk to it (CSRF) or rebind a DNS name to 127.0.0.1. Defences, all
mandatory: loopback bind, per-session random token compared in constant time, exact
Host/Origin allowlists (never wildcard), lockout with backoff on failed token attempts.
"""
from __future__ import annotations

import hmac
import ipaddress
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

COOKIE_NAME = "cr_session"
UNSAFE_BIND_WARNING = (
    "\n"
    "!!! WARNING: --unsafe-bind is set. The CogniRepo control API is listening on a NON-LOOPBACK\n"
    "!!! address. Anyone who can reach this port and obtain the session token can start/stop\n"
    "!!! services and read your knowledge graph. Do not do this on a shared or untrusted network.\n"
)


class UnsafeBindError(ValueError):
    """Raised when asked to bind a non-loopback address without --unsafe-bind."""


def is_loopback_host(host: str) -> bool:
    """True for 127.0.0.0/8, ::1 and the literal name ``localhost``. 0.0.0.0 is NOT loopback."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_bind_host(host: str, unsafe: bool = False) -> str | None:
    """Return None for a safe bind, or the loud warning text for an explicitly unsafe one.

    Raises UnsafeBindError for a non-loopback host without ``unsafe``.
    """
    if is_loopback_host(host):
        return None
    if not unsafe:
        raise UnsafeBindError(
            f"refusing to bind {host!r}: the control API is loopback-only. "
            "Use 127.0.0.1, or pass --unsafe-bind if you really mean it."
        )
    return UNSAFE_BIND_WARNING


def new_token() -> str:
    """A fresh random per-session token."""
    return secrets.token_urlsafe(32)


def tokens_equal(supplied: str | None, expected: str) -> bool:
    """Constant-time comparison; never raises on odd input."""
    if not supplied:
        return False
    return hmac.compare_digest(supplied.encode("utf-8", "replace"), expected.encode("utf-8"))


def allowed_hosts(port: int) -> frozenset[str]:
    """Exact ``Host`` header values accepted (blocks DNS rebinding)."""
    return frozenset({f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"})


def allowed_origins(port: int, extra: tuple[str, ...] = ()) -> frozenset[str]:
    """Exact ``Origin`` values accepted. ``extra`` must be explicit origins, never ``*``."""
    base = {f"http://127.0.0.1:{port}", f"http://localhost:{port}", f"http://[::1]:{port}"}
    for origin in extra:
        if origin.strip() == "*" or not origin.startswith(("http://", "https://")):
            raise ValueError(f"invalid --allow-origin {origin!r}: must be an exact http(s) origin, no wildcard")
        base.add(origin.rstrip("/"))
    return frozenset(base)


def extract_token(headers: Mapping[str, str], cookies: Mapping[str, str]) -> str | None:
    """Bearer header wins; otherwise the httpOnly session cookie."""
    auth = headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip() or None
    return cookies.get(COOKIE_NAME) or None


@dataclass
class _State:
    failures: int = 0
    strikes: int = 0
    locked_until: float = 0.0


class AttemptLimiter:
    """Lock out a client after repeated bad tokens, with exponential backoff.

    ``max_failures`` bad attempts => locked for ``base_lockout * 2**(strikes-1)`` seconds
    (capped at ``max_lockout``). While locked even a correct token is refused, so the lock
    cannot be probed. A success clears the client's state.
    """

    _MAX_CLIENTS = 1024

    def __init__(self, max_failures: int = 5, base_lockout: float = 5.0,
                 max_lockout: float = 300.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.max_failures = max_failures
        self.base_lockout = base_lockout
        self.max_lockout = max_lockout
        self._clock = clock
        self._lock = threading.Lock()
        self._states: dict[str, _State] = {}

    def retry_after(self, client: str) -> float:
        """Seconds until ``client`` may try again (0 when not locked)."""
        with self._lock:
            st = self._states.get(client)
            if st is None:
                return 0.0
            return max(0.0, st.locked_until - self._clock())

    def record_failure(self, client: str) -> None:
        with self._lock:
            if client not in self._states and len(self._states) >= self._MAX_CLIENTS:
                self._states.pop(next(iter(self._states)))
            st = self._states.setdefault(client, _State())
            st.failures += 1
            if st.failures >= self.max_failures:
                st.strikes += 1
                st.failures = 0
                delay = min(self.max_lockout, self.base_lockout * 2 ** (st.strikes - 1))
                st.locked_until = self._clock() + delay

    def record_success(self, client: str) -> None:
        with self._lock:
            self._states.pop(client, None)


@dataclass
class SecurityConfig:
    """Everything the request guard needs, fixed at server start."""

    token: str
    port: int
    extra_origins: tuple[str, ...] = ()
    limiter: AttemptLimiter = field(default_factory=AttemptLimiter)

    def __post_init__(self) -> None:
        self.hosts = allowed_hosts(self.port)
        self.origins = allowed_origins(self.port, self.extra_origins)

    def host_ok(self, host_header: str | None) -> bool:
        return bool(host_header) and host_header.lower() in self.hosts

    def origin_ok(self, origin_header: str | None) -> bool:
        """No Origin header = non-browser client (still needs the token). ``null`` is rejected."""
        if origin_header is None:
            return True
        return origin_header.rstrip("/") in self.origins
