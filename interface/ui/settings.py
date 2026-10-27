# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""The repo settings the control API may change in ``config.json``: ``watch.auto_enabled`` (#211) and
``storage.graph_backend``.

Everything else in ``config.json`` is left untouched (read-modify-write under the store lock, atomic
replace). Reading is in ``interface.ui.repos`` (strictly read-only); this is the only writer.
"""
from __future__ import annotations

import json
import os

from core.config.store_settings import SettingsError, set_value

__all__ = ["SettingsError", "explicit_auto_index", "set_auto_index", "set_graph_backend"]


def explicit_auto_index(store: str) -> bool:
    """True only when ``watch.auto_enabled`` is explicitly ``true`` (absent means the default, which
    the MCP server treats as on but ``cognirepo ui`` does NOT act on at start)."""
    try:
        with open(os.path.join(store, "config.json"), encoding="utf-8") as fh:
            watch = json.load(fh).get("watch")
    except (OSError, ValueError, AttributeError):
        return False
    return isinstance(watch, dict) and watch.get("auto_enabled") is True


def set_auto_index(store: str, enabled: bool) -> bool:
    """Persist ``watch.auto_enabled``. Returns whether the stored value changed."""
    return set_value(store, "watch", "auto_enabled", enabled)


def set_graph_backend(store: str, backend: str) -> bool:
    """Persist ``storage.graph_backend`` (``networkx`` or ``sqlite``). Returns whether it changed."""
    return set_value(store, "storage", "graph_backend", backend)
