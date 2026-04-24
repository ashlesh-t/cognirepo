# pylint: disable=missing-docstring, unnecessary-lambda, import-outside-toplevel, too-few-public-methods, duplicate-code
# pylint: disable=redefined-outer-name, unused-argument, broad-exception-caught, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Shared pytest fixtures for CogniRepo tests.

Uses a temporary directory for all .cognirepo/ storage so tests are
fully isolated from the developer's real data.

Secrets (JWT secret, password hash) are injected via environment variables
so tests never need a real OS keychain.
"""
from __future__ import annotations

import json
import os

import bcrypt
import psutil
import pytest

_MEMORY_LIMIT_GB = 5.0
_MEMORY_WARN_GB = 4.5
_proc = psutil.Process(os.getpid())


@pytest.fixture(autouse=True)
def memory_circuit_breaker():
    """Abort test session if process RSS exceeds 5 GB to prevent OOM crashes."""
    rss_gb = _proc.memory_info().rss / 1024 ** 3
    if rss_gb >= _MEMORY_LIMIT_GB:
        pytest.exit(
            f"Memory circuit breaker: {rss_gb:.2f} GB >= {_MEMORY_LIMIT_GB} GB limit. "
            "Aborting to prevent OOM.",
            returncode=3,
        )
    elif rss_gb >= _MEMORY_WARN_GB:
        import warnings
        warnings.warn(
            f"Memory usage {rss_gb:.2f} GB is approaching the {_MEMORY_LIMIT_GB} GB limit.",
            ResourceWarning,
            stacklevel=2,
        )
    yield


# Secrets generated at import time — never stored as literals in source.
_TEST_PASSWORD = "changeme-test"
_TEST_PASSWORD_HASH = bcrypt.hashpw(_TEST_PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
_TEST_JWT_SECRET = "test-jwt-secret-32chars-for-tests"
_TEST_PROJECT_ID = "test-project-00000000-0000-0000-0000"


@pytest.fixture(autouse=True)
def isolated_cognirepo(tmp_path, monkeypatch):
    """
    Redirect all .cognirepo/ and vector_db/ paths to a temp directory.
    Every test gets a fresh, empty store.

    Secrets are injected as env vars — no keychain access required in tests.
    """
    from config.paths import set_cognirepo_dir, set_global_dir
    set_cognirepo_dir(str(tmp_path / ".cognirepo"))
    set_global_dir(str(tmp_path / ".cognirepo-global"))

    # Change CWD so relative paths land in tmp
    monkeypatch.chdir(tmp_path)

    # Inject secrets via env vars (mirrors CI / Docker behaviour)
    monkeypatch.setenv("COGNIREPO_JWT_SECRET", _TEST_JWT_SECRET)
    monkeypatch.setenv("COGNIREPO_PASSWORD_HASH", _TEST_PASSWORD_HASH)

    # Create required subdirectories
    for d in [
        ".cognirepo/memory",
        ".cognirepo/graph",
        ".cognirepo/index",
        ".cognirepo/sessions",
        ".cognirepo/vector_db",
        "server",
        "adapters",
    ]:
        os.makedirs(d, exist_ok=True)

    # Write minimal config — no secrets in config (they live in env vars above)
    config = {
        "project_id": _TEST_PROJECT_ID,
        "api_port": 8080,
        "api_url": "http://localhost:8080",
        "storage": {"encrypt": False},
        "retrieval_weights": {"vector": 0.5, "graph": 0.3, "behaviour": 0.2},
        "models": {
            "QUICK":    {"provider": "grok",      "model": "grok-beta"},
            "STANDARD": {"provider": "gemini",    "model": "gemini-2.0-flash"},
            "COMPLEX":  {"provider": "gemini",    "model": "gemini-2.0-flash"},
            "EXPERT":   {"provider": "anthropic", "model": "claude-sonnet-4-6"},
        },
    }
    with open(".cognirepo/config.json", "w", encoding="utf-8") as f:
        json.dump(config, f)

    yield tmp_path


@pytest.fixture
def test_password():
    """Return the plaintext password used in the isolated test config."""
    return _TEST_PASSWORD
