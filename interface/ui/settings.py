# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""The one repo setting the control API may change: ``watch.auto_enabled`` in ``config.json`` (#211).

Everything else in ``config.json`` is left untouched (read-modify-write under the store lock, atomic
replace). Reading is in ``interface.ui.repos`` (strictly read-only); this is the only writer.
"""
from __future__ import annotations

import json
import os
from typing import Any

from core.config.atomic import atomic_json_dump
from core.config.lock import store_lock


class SettingsError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


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
    path = os.path.join(store, "config.json")
    with store_lock(lock_path=os.path.join(store, "cognirepo.lock")):
        try:
            with open(path, encoding="utf-8") as fh:
                cfg: Any = json.load(fh)
        except FileNotFoundError as exc:
            raise SettingsError("not_initialised", "no config.json for this repo; run `cognirepo init`") from exc
        except (OSError, ValueError) as exc:
            raise SettingsError("config_unreadable", "config.json could not be read; nothing was changed") from exc
        if not isinstance(cfg, dict):
            raise SettingsError("config_unreadable", "config.json is not an object; nothing was changed")
        watch = cfg.get("watch")
        if not isinstance(watch, dict):
            watch = {}
        changed = watch.get("auto_enabled") is not enabled
        watch["auto_enabled"] = enabled
        cfg["watch"] = watch
        if changed:
            atomic_json_dump(path, cfg)
        return changed
