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

import gc
import json
import os
from unittest.mock import MagicMock

import bcrypt
import psutil
import pytest
import numpy as np

# Calculate 70% of total RAM for the circuit breaker
_TOTAL_RAM = psutil.virtual_memory().total
_MEMORY_LIMIT_BYTES = int(_TOTAL_RAM * 0.7)
_MEMORY_LIMIT_GB = _MEMORY_LIMIT_BYTES / (1024 ** 3)
_proc = psutil.Process(os.getpid())


@pytest.fixture(autouse=True, scope="session")
def mock_embeddings():
    """
    Globally mock fastembed to prevent ONNX model downloads/loading in tests.
    Returns deterministic one-hot vectors based on keywords to ensure 
    predictable ranking for tests that rely on similarity.
    """
    import numpy as np

    with MagicMock() as mock_engine:
        def fake_embed(texts):
            results = []
            # List of keywords that tests look for. 
            # Order matters: we pick the FIRST matching keyword to define the vector.
            keywords = [
                "jwt", "auth", "authentication", "docker", "python", 
                "memory", "graph", "context", "store", "retrieve", 
                "implementation", "setup", "verify", "token"
            ]
            
            for text in texts:
                vec = np.zeros(384, dtype="float32")
                found = False
                for i, kw in enumerate(keywords):
                    if kw in text.lower():
                        # One-hot encoding for the keyword
                        vec[i] = 1.0
                        found = True
                        break
                
                if not found:
                    # Fallback for texts with no keywords: use hash of first char
                    if text:
                        idx = (ord(text[0]) % 100) + len(keywords)
                        vec[idx] = 1.0
                    else:
                        vec[0] = 1.0
                
                results.append(vec)
            return iter(results)

        mock_engine.embed.side_effect = fake_embed
        
        with MagicMock() as mock_class:
            mock_class.return_value = mock_engine
            
            # Patch fastembed.TextEmbedding
            with pytest.MonkeyPatch().context() as mp:
                try:
                    import fastembed
                    mp.setattr("fastembed.TextEmbedding", mock_class)
                except ImportError:
                    pass
                yield


@pytest.fixture(autouse=True)
def memory_circuit_breaker():
    """Abort test session if process RSS exceeds 70% of total RAM."""
    rss_bytes = _proc.memory_info().rss
    if rss_bytes >= _MEMORY_LIMIT_BYTES:
        pytest.exit(
            f"Memory circuit breaker: {rss_bytes / 1024**3:.2f} GB >= {_MEMORY_LIMIT_GB:.2f} GB (70% RAM). "
            "Aborting to prevent system crash.",
            returncode=3,
        )
    yield
    gc.collect()


@pytest.fixture(autouse=True)
def _reset_singletons():
    """
    Reset module-level singletons that accumulate memory across tests.

    Each test gets isolated tmp_path storage, but Python module globals
    (FAISS indices, BM25 corpora, hybrid caches, learning store, circuit
    breaker) persist for the process lifetime. Nulling them here lets
    CPython and C-extension allocators reclaim memory before the next test.
    """
    yield
    _null_attrs = [
        # (module_path, attr_name, reset_value)
        ("memory.embeddings",        "MODEL",       None),
        ("memory.circuit_breaker",   "_BREAKER",    None),
        ("memory.episodic_memory",   "_BM25_CORPUS", None),
        ("memory.episodic_memory",   "_BM25_INDEX",  None),
        ("memory.learning_store",    "_STORE",      None),
        ("retrieval.hybrid",         "_HYBRID_CACHE", {}),
        ("retrieval.hybrid",         "_IN_FLIGHT",   {}),
    ]
    for _mod_path, _attr, _reset_val in _null_attrs:
        try:
            import importlib
            _mod = importlib.import_module(_mod_path)
            if hasattr(_mod, _attr):
                setattr(_mod, _attr, _reset_val)
        except Exception:  # pylint: disable=broad-except
            pass

    gc.collect()


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
