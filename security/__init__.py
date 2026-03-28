# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
CogniRepo security package.

Provides helpers for encryption-at-rest and credential management.
Encryption is opt-in via  storage.encrypt: true  in .cognirepo/config.json.
"""
import json
import os


def get_project_id() -> str:
    """
    Return the project_id stored in .cognirepo/config.json.
    Falls back to the CWD basename if the config is missing or malformed.
    """
    config_path = ".cognirepo/config.json"
    try:
        with open(config_path, encoding="utf-8") as f:
            return json.load(f).get(
                "project_id",
                os.path.basename(os.path.abspath(os.getcwd())),
            )
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return os.path.basename(os.path.abspath(os.getcwd()))


def get_storage_config() -> tuple[bool, str]:
    """
    Return (should_encrypt, project_id) from .cognirepo/config.json.
    Returns (False, "") when the config is absent or encryption is disabled.
    """
    config_path = ".cognirepo/config.json"
    try:
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
        encrypt = bool(cfg.get("storage", {}).get("encrypt", False))
        project_id = cfg.get(
            "project_id",
            os.path.basename(os.path.abspath(os.getcwd())),
        )
        return encrypt, project_id
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False, ""
