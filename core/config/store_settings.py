# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Write one value into a repo's ``config.json`` without disturbing the rest of it.

Read-modify-write under the store lock, atomic replace, nothing else touched. Used by the control API's
settings (``watch.auto_enabled``) and by the graph-backend switch (``storage.graph_backend``), and by the CLI's
``graph migrate`` so a migration and a toggle change the setting the same way.
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


def set_value(store: str, section: str, key: str, value: Any) -> bool:
    """Persist ``config.json[section][key] = value`` for the repo whose ``.cognirepo`` is *store*.
    Returns whether the stored value changed. Raises ``SettingsError`` (nothing written) if the config is
    missing or unreadable."""
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
        block = cfg.get(section)
        if not isinstance(block, dict):
            block = {}
        changed = block.get(key) is not value and block.get(key) != value
        block[key] = value
        cfg[section] = block
        if changed:
            atomic_json_dump(path, cfg)
        return changed
