# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Runtime version metadata — reads version.yml so all code shares one source of truth.
Do NOT hardcode version strings elsewhere; import from here instead.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent


@lru_cache(maxsize=1)
def _load() -> dict:
    version_file = _REPO_ROOT / "version.yml"
    try:
        import yaml  # type: ignore[import-untyped]
        with version_file.open() as f:
            return yaml.safe_load(f)
    except Exception:
        return {}


def _project(key: str, fallback: str = "") -> str:
    return _load().get("project", {}).get(key, fallback)


__version__: str = _project("version", "1.1.3")
APP_NAME: str = _project("name", "cognirepo")
DESCRIPTION: str = _project("description", "Local cognitive infrastructure layer for AI agents")
LICENSE: str = _project("license", "MIT")

REPO_URL: str = _load().get("repository", {}).get("url", "https://github.com/ashlesh-t/cognirepo")
MCP_NAME: str = _load().get("repository", {}).get("mcp_name", "io.github.ashlesh-t/cognirepo")
MCP_TITLE: str = _load().get("mcp", {}).get("title", "CogniRepo")
