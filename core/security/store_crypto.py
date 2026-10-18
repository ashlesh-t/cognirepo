# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Shared at-rest encryption for single-file JSON stores (#186).

``encode_store`` / ``decode_store`` are the one read/write pair for stores that were
plaintext before encryption covered them (learnings, project memory, AST index metadata).

Read rules (the same ones the graph / episodic stores already follow):
  * a Fernet token is always decrypted, whatever the current ``storage.encrypt`` flag says —
    turning the flag off must never strand data;
  * plaintext is returned as-is (the store predates the flag; it is encrypted on the next save);
  * a token that cannot be decrypted (no keyring, wrong key) raises ``StoreUnreadableError``
    with ``locked=True`` — intact ciphertext is never treated as corruption, so it is never
    quarantined or overwritten.
"""
from __future__ import annotations

import logging

from core.config.safe_read import StoreUnreadableError, looks_encrypted

logger = logging.getLogger(__name__)


def _key_for(key_id: str | None) -> bytes:
    from core.security import get_project_id  # pylint: disable=import-outside-toplevel
    from core.security.encryption import get_or_create_key  # pylint: disable=import-outside-toplevel
    return get_or_create_key(key_id or get_project_id())


def encryption_enabled() -> bool:
    """True when the active repo's config has ``storage.encrypt: true``."""
    from core.security import get_storage_config  # pylint: disable=import-outside-toplevel
    return get_storage_config()[0]


def encode_store(data: bytes, *, key_id: str | None = None, enabled: bool | None = None) -> bytes:
    """Encrypt ``data`` when encryption is enabled; otherwise return it unchanged.

    ``key_id`` names the keychain entry. Repo-local stores use the default (the repo's
    ``project_id``); stores shared by several repos (global learnings, org project memory)
    pass their own id so every repo on the machine can read them. ``enabled`` overrides the
    config flag (used by the explicit ``cognirepo encrypt-stores`` migration).
    """
    if not (encryption_enabled() if enabled is None else enabled):
        return data
    from core.security.encryption import encrypt_bytes  # pylint: disable=import-outside-toplevel
    return encrypt_bytes(data, _key_for(key_id))


def decode_store(raw: bytes, path: str, *, key_id: str | None = None) -> bytes:
    """Return the plaintext of a store file's bytes (see the module docstring for the rules)."""
    if not looks_encrypted(raw):
        return raw
    try:
        from core.security.encryption import decrypt_bytes  # pylint: disable=import-outside-toplevel
        return decrypt_bytes(raw, _key_for(key_id))
    except Exception as exc:  # pylint: disable=broad-except
        raise StoreUnreadableError(
            path, f"encrypted and cannot be decrypted ({type(exc).__name__})", locked=True,
        ) from exc
