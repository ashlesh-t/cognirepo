# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
CogniRepo security package.

Provides helpers for encryption-at-rest and credential management.
Encryption is opt-in via  storage.encrypt: true  in .cognirepo/config.json.
"""
import json
import os


def _config_path() -> str:
    """Resolve config.json via the active repo context (_CTX_DIR), not bare CWD.

    A context-switched operation (org indexing, repo_path tool calls) was
    reading the WRONG repo's config here, causing graph/metadata to be
    written plaintext while the owning repo's config says encrypt=true —
    which then made every later load fail decryption and silently start
    with an empty graph.
    """
    try:
        from core.config.paths import get_path  # pylint: disable=import-outside-toplevel
        return get_path("config.json")
    except Exception:  # pylint: disable=broad-except
        return ".cognirepo/config.json"


def get_project_id() -> str:
    """
    Return the project_id stored in .cognirepo/config.json.
    Falls back to the CWD basename if the config is missing or malformed.
    """
    config_path = _config_path()
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
    config_path = _config_path()
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
