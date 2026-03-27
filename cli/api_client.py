# SPDX-FileCopyrightText: 2026 Ashlesh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/your-username/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Thin HTTP wrapper around the CogniRepo REST API.

Used by cli/main.py when --via-api is passed.
Token acquisition order:
  1. COGNIREPO_TOKEN env var (pre-issued token)
  2. COGNIREPO_PASSWORD env var (password → /login)
  3. Interactive getpass prompt
"""
import getpass
import json
import os
import sys

import httpx

CONFIG_FILE = ".cognirepo/config.json"
DEFAULT_URL = "http://localhost:8000"


def _get_api_url(override: str = None) -> str:
    if override:
        return override.rstrip("/")
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("api_url", DEFAULT_URL).rstrip("/")
    return DEFAULT_URL


def _acquire_token(api_url: str) -> str:
    token = os.environ.get("COGNIREPO_TOKEN")
    if token:
        return token

    password = os.environ.get("COGNIREPO_PASSWORD") or getpass.getpass("CogniRepo API password: ")
    try:
        resp = httpx.post(f"{api_url}/login", json={"password": password}, timeout=10)
    except httpx.ConnectError:
        print(f"Cannot reach CogniRepo API at {api_url} — is `uvicorn api.main:app` running?", file=sys.stderr)
        sys.exit(1)

    if resp.status_code != 200:
        print(f"Login failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        sys.exit(1)

    return resp.json()["access_token"]


def _req(method: str, url: str, token: str, **kwargs):
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = httpx.request(method, url, headers=headers, timeout=15, **kwargs)
    except httpx.ConnectError:
        print(f"Lost connection to CogniRepo API at {url}", file=sys.stderr)
        sys.exit(1)

    if not resp.is_success:
        print(f"API error {resp.status_code}: {resp.text}", file=sys.stderr)
        sys.exit(1)

    return resp.json()


class ApiClient:
    """Lazily authenticates on first request."""

    def __init__(self, api_url: str = None):
        self.url = _get_api_url(api_url)
        self._token: str | None = None

    @property
    def token(self) -> str:
        if not self._token:
            self._token = _acquire_token(self.url)
        return self._token

    def store_memory(self, text: str, source: str = "") -> dict:
        return _req("POST", f"{self.url}/memory/store", self.token,
                    json={"text": text, "source": source})

    def retrieve_memory(self, query: str, top_k: int = 5) -> list:
        return _req("POST", f"{self.url}/memory/retrieve", self.token,
                    json={"query": query, "top_k": top_k})

    def search_docs(self, query: str) -> list:
        return _req("GET", f"{self.url}/memory/search", self.token,
                    params={"q": query})

    def log_episode(self, event: str, metadata: dict = None) -> dict:
        return _req("POST", f"{self.url}/episodic/log", self.token,
                    json={"event": event, "metadata": metadata or {}})

    def get_history(self, limit: int = 100) -> list:
        return _req("GET", f"{self.url}/episodic/history", self.token,
                    params={"limit": limit})
