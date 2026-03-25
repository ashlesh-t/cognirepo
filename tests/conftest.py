"""
Shared pytest fixtures for CogniRepo tests.

Uses a temporary directory for all .cognirepo/ storage so tests are
fully isolated from the developer's real data.
"""
from __future__ import annotations

import json
import os
import tempfile

import pytest


@pytest.fixture(autouse=True)
def isolated_cognirepo(tmp_path, monkeypatch):
    """
    Redirect all .cognirepo/ and vector_db/ paths to a temp directory.
    Every test gets a fresh, empty store.
    """
    # Change CWD so relative paths (.cognirepo/, vector_db/) land in tmp
    monkeypatch.chdir(tmp_path)

    # Create required subdirectories
    for d in [
        ".cognirepo/memory",
        ".cognirepo/graph",
        ".cognirepo/index",
        ".cognirepo/sessions",
        "vector_db",
        "server",
        "adapters",
    ]:
        os.makedirs(d, exist_ok=True)

    # Write minimal config
    config = {
        "password_hash": "$2b$12$t45Vid98P7hCZYno6x/CreyrkCdaFohPSc37fDq9lfRLUb5Ypre6e",
        "api_port": 8080,
        "api_url": "http://localhost:8080",
        "retrieval_weights": {"vector": 0.5, "graph": 0.3, "behaviour": 0.2},
        "models": {
            "FAST":     {"provider": "gemini",    "model": "gemini-2.0-flash"},
            "BALANCED": {"provider": "gemini",    "model": "gemini-2.0-flash"},
            "DEEP":     {"provider": "anthropic", "model": "claude-sonnet-4-6"},
        },
    }
    with open(".cognirepo/config.json", "w") as f:
        json.dump(config, f)

    yield tmp_path
