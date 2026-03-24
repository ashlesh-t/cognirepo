"""
/login endpoint — returns a 24-hour HS256 JWT on valid password.
Password is stored bcrypt-hashed in .cognirepo/config.json.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

SECRET_KEY = os.environ.get("COGNIREPO_SECRET", "dev-secret-change-me")
ALGORITHM = "HS256"
CONFIG_FILE = ".cognirepo/config.json"

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    password: str


def _get_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        raise HTTPException(status_code=500, detail="CogniRepo not initialised — run `cognirepo init`")
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


@router.post("/login")
def login(req: LoginRequest):
    """Exchange a password for a bearer JWT valid for 24 hours."""
    config = _get_config()
    pw_hash: str = config.get("password_hash", "")
    if not pw_hash:
        raise HTTPException(status_code=500, detail="No password configured")

    if not bcrypt.checkpw(req.password.encode(), pw_hash.encode()):
        raise HTTPException(status_code=401, detail="Invalid password")

    now = datetime.now(tz=timezone.utc)
    token = jwt.encode(
        {"sub": "user", "iat": now, "exp": now + timedelta(hours=24)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    return {"access_token": token, "token_type": "bearer"}
