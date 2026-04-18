# pylint: disable=missing-docstring, unnecessary-lambda, import-outside-toplevel, too-few-public-methods, duplicate-code
# pylint: disable=redefined-outer-name, unused-argument, broad-exception-caught, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_encryption.py — Sprint 1.1 acceptance criteria.

Covers:
  - Fernet round-trip: write encrypted → read decrypted = original bytes
  - Key persistence: second call returns same key (mock keyring)
  - Encryption disabled: plaintext write/read unchanged
  - Missing cryptography + encrypt: true → ImportError with install hint
"""
from __future__ import annotations

import json
import sys
from unittest import mock

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _enable_encryption(tmp_path):
    """Write a config.json with storage.encrypt: true and a fixed project_id."""
    config = {
        "project_id": "test-project-enc",
        "api_port": 8080,
        "api_url": "http://localhost:8080",
        "storage": {"encrypt": True},
        "retrieval_weights": {"vector": 0.5, "graph": 0.3, "behaviour": 0.2},
        "models": {},
    }
    with open(".cognirepo/config.json", "w", encoding="utf-8") as f:
        json.dump(config, f)


def _disable_encryption(tmp_path):
    """Write a config.json with storage.encrypt: false."""
    config = {
        "project_id": "test-project-plain",
        "api_port": 8080,
        "api_url": "http://localhost:8080",
        "storage": {"encrypt": False},
        "retrieval_weights": {"vector": 0.5, "graph": 0.3, "behaviour": 0.2},
        "models": {},
    }
    with open(".cognirepo/config.json", "w", encoding="utf-8") as f:
        json.dump(config, f)


# ── unit tests for encryption.py ─────────────────────────────────────────────

class TestFernetHelpers:
    """Direct unit tests for the encryption module."""

    def test_encrypt_decrypt_round_trip(self):
        pytest.importorskip("cryptography")
        from security.encryption import get_or_create_key, encrypt_bytes, decrypt_bytes

        with mock.patch("keyring.get_password", return_value=None), \
             mock.patch("keyring.set_password"):
            key = get_or_create_key("proj-test")

        original = b"sensitive developer memory data"
        ciphertext = encrypt_bytes(original, key)
        assert ciphertext != original
        assert decrypt_bytes(ciphertext, key) == original

    def test_key_persistence_returns_same_key(self):
        """Second call with same project_id returns the same key."""
        pytest.importorskip("cryptography")
        from security.encryption import get_or_create_key

        stored_key = None

        def fake_set(service, project_id, value):
            nonlocal stored_key
            stored_key = value

        def fake_get(service, project_id):
            return stored_key

        with mock.patch("keyring.get_password", side_effect=fake_get), \
             mock.patch("keyring.set_password", side_effect=fake_set):
            key1 = get_or_create_key("my-project")
            key2 = get_or_create_key("my-project")

        assert key1 == key2

    def test_missing_cryptography_raises_import_error(self, monkeypatch):
        """When cryptography is not installed, a clear ImportError is raised."""
        # Remove cryptography from sys.modules to simulate missing dep
        monkeypatch.setitem(sys.modules, "cryptography", None)
        monkeypatch.setitem(sys.modules, "cryptography.fernet", None)

        # Re-import to force fresh execution of _require_deps
        if "security.encryption" in sys.modules:
            del sys.modules["security.encryption"]

        from security import encryption  # re-import
        with pytest.raises(ImportError, match="pip install 'cognirepo\\[security\\]'"):
            encryption._require_deps()


# ── integration: episodic_memory ─────────────────────────────────────────────

class TestEpisodicEncryption:
    def test_encrypt_write_not_plaintext(self, isolated_cognirepo):
        pytest.importorskip("cryptography")
        _enable_encryption(isolated_cognirepo)

        key_store: dict = {}

        def fake_get(svc, proj):
            return key_store.get(proj)

        def fake_set(svc, proj, val):
            key_store[proj] = val

        with mock.patch("keyring.get_password", side_effect=fake_get), \
             mock.patch("keyring.set_password", side_effect=fake_set):
            from memory.episodic_memory import log_event
            log_event("test sensitive event", {"detail": "secret"})

        # Raw bytes must NOT contain the plaintext
        with open(".cognirepo/memory/episodic.json", "rb") as f:
            raw = f.read()
        assert b"test sensitive event" not in raw

    def test_encrypt_round_trip(self, isolated_cognirepo):
        """Write encrypted → read decrypted = original event."""
        pytest.importorskip("cryptography")
        _enable_encryption(isolated_cognirepo)

        key_store: dict = {}

        def fake_get(svc, proj):
            return key_store.get(proj)

        def fake_set(svc, proj, val):
            key_store[proj] = val

        with mock.patch("keyring.get_password", side_effect=fake_get), \
             mock.patch("keyring.set_password", side_effect=fake_set):
            from memory import episodic_memory
            # Force module reload so get_storage_config is re-evaluated
            import importlib
            importlib.reload(episodic_memory)
            episodic_memory.log_event("round-trip check", {"x": 1})
            history = episodic_memory.get_history(limit=10)

        assert any("round-trip check" in e["event"] for e in history)

    def test_disabled_encryption_plaintext(self, isolated_cognirepo):
        """When encryption is disabled, file is human-readable JSON."""
        _disable_encryption(isolated_cognirepo)

        from memory.episodic_memory import log_event
        log_event("plaintext event")

        with open(".cognirepo/memory/episodic.json", "rb") as f:
            raw = f.read()
        assert b"plaintext event" in raw


# ── integration: knowledge_graph ─────────────────────────────────────────────

class TestGraphEncryption:
    def test_graph_pkl_encrypted(self, isolated_cognirepo):
        pytest.importorskip("cryptography")
        _enable_encryption(isolated_cognirepo)

        key_store: dict = {}

        def fake_get(svc, proj):
            return key_store.get(proj)

        def fake_set(svc, proj, val):
            key_store[proj] = val

        with mock.patch("keyring.get_password", side_effect=fake_get), \
             mock.patch("keyring.set_password", side_effect=fake_set):
            from graph.knowledge_graph import KnowledgeGraph
            kg = KnowledgeGraph()
            kg.add_node("fn::secret_func", "FUNCTION")
            kg.save()

        with open(".cognirepo/graph/graph.pkl", "rb") as f:
            raw = f.read()
        # Fernet token starts with gAAAAA — definitely not a pickle header
        assert not raw.startswith(b"\x80")  # pickle magic byte

    def test_graph_disabled_encryption_is_pickle(self, isolated_cognirepo):
        _disable_encryption(isolated_cognirepo)

        from graph.knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph()
        kg.add_node("fn::visible_func", "FUNCTION")
        kg.save()

        with open(".cognirepo/graph/graph.pkl", "rb") as f:
            raw = f.read()
        assert raw.startswith(b"\x80")  # valid pickle header


# ── gitignore blanket pattern ─────────────────────────────────────────────────

class TestGitignoreBlanket:
    def test_gitignore_blanket_pattern(self, isolated_cognirepo):
        """cognirepo init must write * as the primary gitignore pattern."""
        from cli.init_project import init_project
        with mock.patch("builtins.input", return_value="n"):
            init_project(no_index=True)

        with open(".cognirepo/.gitignore", encoding="utf-8") as f:
            content = f.read()
        assert "*" in content
        assert "!.gitignore" in content
