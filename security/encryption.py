# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Fernet-based encryption helpers for CogniRepo at-rest storage.

Keys are stored in the OS keychain (via keyring) — never written to disk.
Both  cryptography  and  keyring  are optional deps:
  pip install 'cognirepo[security]'

Usage:
  from security.encryption import get_or_create_key, encrypt_bytes, decrypt_bytes
"""

SERVICE_NAME = "cognirepo"


def _require_deps():
    """Import and return (Fernet, keyring), raising a clear error if missing."""
    try:
        from cryptography.fernet import Fernet  # pylint: disable=import-outside-toplevel
        import keyring  # pylint: disable=import-outside-toplevel
        return Fernet, keyring
    except ImportError as exc:
        raise ImportError(
            "Encryption requires additional packages. "
            "Run: pip install 'cognirepo[security]'"
        ) from exc


def get_or_create_key(project_id: str) -> bytes:
    """
    Retrieve the Fernet encryption key for *project_id* from the OS keychain.
    If no key exists yet, generate one, persist it, and return it.
    The key is NEVER written to any file on disk.
    """
    fernet_cls, keyring = _require_deps()
    stored = keyring.get_password(SERVICE_NAME, project_id)
    if stored:
        return stored.encode()
    key = fernet_cls.generate_key()
    keyring.set_password(SERVICE_NAME, project_id, key.decode())
    return key


def encrypt_bytes(data: bytes, key: bytes) -> bytes:
    """Encrypt *data* with the given Fernet *key*."""
    fernet_cls, _ = _require_deps()
    return fernet_cls(key).encrypt(data)


def decrypt_bytes(data: bytes, key: bytes) -> bytes:
    """Decrypt *data* with the given Fernet *key*."""
    fernet_cls, _ = _require_deps()
    return fernet_cls(key).decrypt(data)
