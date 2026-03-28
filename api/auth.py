# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
/login endpoint — returns a 24-hour HS256 JWT on valid password.

Secret resolution order (both jwt_secret and password_hash):
  1. Environment variable   COGNIREPO_JWT_SECRET / COGNIREPO_PASSWORD_HASH
  2. OS keychain            keyring.get_password("<password>", "<project_id>.jwt_secret")
  3. config.json fallback   password_hash field (backward-compat for existing installs)
"""
import json
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from security import get_project_id

ALGORITHM = "HS256"
CONFIG_FILE = ".cognirepo/config.json"
_KEYCHAIN_SERVICE = "cognirepo"

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):  # pylint: disable=too-few-public-methods
    """Request body for /login — just a password."""
    password: str


# ── secret resolution helpers ─────────────────────────────────────────────────

def _keychain_get(key: str) -> str | None:
    try:
        import keyring  # pylint: disable=import-outside-toplevel
        return keyring.get_password(_KEYCHAIN_SERVICE, key)
    except Exception:  # pylint: disable=broad-except
        return None


def get_jwt_secret() -> str:
    """Resolve the JWT signing secret from env → keychain → error."""
    secret = os.getenv("COGNIREPO_JWT_SECRET")
    if secret:
        return secret
    stored = _keychain_get(f"{get_project_id()}.jwt_secret")
    if stored:
        return stored
    raise RuntimeError(
        "JWT secret not found. Run 'cognirepo init' first, "
        "or set COGNIREPO_JWT_SECRET."
    )


def _get_password_hash() -> str:
    """Resolve the bcrypt password hash from env → keychain → config fallback."""
    pw_hash = os.environ.get("COGNIREPO_PASSWORD_HASH")
    if pw_hash:
        return pw_hash
    stored = _keychain_get(f"{get_project_id()}.password_hash")
    if stored:
        return stored
    # Backward-compat: some existing installs still have hash in config.json
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
        pw_hash = cfg.get("password_hash", "")
        if pw_hash:
            return pw_hash
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    raise HTTPException(
        status_code=500,
        detail="No password configured. Run 'cognirepo init'.",
    )


# ── endpoint ──────────────────────────────────────────────────────────────────

@router.post("/login")
def login(req: LoginRequest):
    """Exchange a password for a bearer JWT valid for 24 hours."""
    pw_hash = _get_password_hash()
    if not bcrypt.checkpw(req.password.encode(), pw_hash.encode()):
        raise HTTPException(status_code=401, detail="Invalid password")

    secret = get_jwt_secret()
    now = datetime.now(tz=timezone.utc)
    token = jwt.encode(
        {"sub": "user", "iat": now, "exp": now + timedelta(hours=24)},
        secret,
        algorithm=ALGORITHM,
    )
    return {"access_token": token, "token_type": "bearer"}
