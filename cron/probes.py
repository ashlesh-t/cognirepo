# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Circuit breaker probes — pluggable health checks for the generalized breaker.

Each Probe is a callable returning a ProbeResult namedtuple:
    ok      bool     — True if the subsystem is healthy
    reason  str      — human-readable explanation (shown when ok=False)

Built-in probes:
    RSSProbe(limit_mb)          — original RSS memory check
    DiskFreeProbe(min_free_mb)  — disk-free check on the data dir
    FAISSHealthProbe()          — FAISS index accessible and non-empty
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class ProbeResult:
    """Result from a single circuit-breaker probe."""
    ok: bool
    reason: str = ""


# Type alias for a probe callable
Probe = Callable[[], ProbeResult]


# ── RSS probe (existing behaviour) ────────────────────────────────────────────

def _rss_mb() -> float:
    try:
        with open("/proc/self/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


class RSSProbe:
    """Probe that trips when process RSS exceeds a threshold."""

    def __init__(self, limit_mb: float) -> None:
        self._limit = limit_mb

    def __call__(self) -> ProbeResult:
        rss = _rss_mb()
        if rss >= self._limit:
            return ProbeResult(ok=False, reason=f"RSS {rss:.0f} MB >= limit {self._limit:.0f} MB")
        return ProbeResult(ok=True, reason=f"RSS {rss:.0f} MB < {self._limit:.0f} MB")


# ── disk free probe ───────────────────────────────────────────────────────────

class DiskFreeProbe:
    """Probe that trips when free disk space on the data path drops below min_free_mb."""

    def __init__(self, min_free_mb: float = 500.0, path: str = ".") -> None:
        self._min_free = min_free_mb
        self._path = path

    def __call__(self) -> ProbeResult:
        try:
            stat = os.statvfs(self._path)
            free_mb = (stat.f_bavail * stat.f_frsize) / (1024 * 1024)
            if free_mb < self._min_free:
                return ProbeResult(
                    ok=False,
                    reason=f"Disk free {free_mb:.0f} MB < {self._min_free:.0f} MB on {self._path}",
                )
            return ProbeResult(ok=True, reason=f"Disk free {free_mb:.0f} MB")
        except OSError as exc:
            return ProbeResult(ok=False, reason=f"DiskFreeProbe error: {exc}")


# ── FAISS health probe ────────────────────────────────────────────────────────

class FAISSHealthProbe:
    """Probe that checks the FAISS index is readable and contains vectors."""

    def __call__(self) -> ProbeResult:
        try:
            from config.paths import get_path  # pylint: disable=import-outside-toplevel
            index_path = get_path("vector_db/semantic.index")
            if not os.path.exists(index_path):
                return ProbeResult(ok=True, reason="FAISS index not yet created (normal cold start)")
            import faiss  # pylint: disable=import-outside-toplevel
            index = faiss.read_index(index_path)
            if index.ntotal == 0:
                return ProbeResult(ok=True, reason="FAISS index empty (normal cold start)")
            return ProbeResult(ok=True, reason=f"FAISS index OK ({index.ntotal} vectors)")
        except Exception as exc:  # pylint: disable=broad-except
            return ProbeResult(ok=False, reason=f"FAISS health check failed: {exc}")
