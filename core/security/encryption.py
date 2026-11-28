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


class KeyUnavailableError(RuntimeError):
    """The encryption key cannot be read, or does not fit the data. ``str()`` says why and what to do about it."""


def keyring_backend_name() -> "str | None":
    """``module.Class`` of the active keyring backend, or None when keyring is missing or broken."""
    try:
        import keyring  # pylint: disable=import-outside-toplevel
        backend = keyring.get_keyring()
    except Exception:  # pylint: disable=broad-except
        return None
    return f"{type(backend).__module__}.{type(backend).__name__}"


def is_unusable_backend(backend: "str | None") -> bool:
    """keyring's fail/null backends mean 'no keyring here': every key lookup will error or miss."""
    return bool(backend) and (".backends.fail." in backend or ".backends.null." in backend)


def _no_backend_message(backend: "str | None") -> str:
    return (
        f"there is no usable keyring backend here ({backend}), so the encryption key cannot be read. "
        "keyring and cryptography are installed; the key itself is kept in the OS keychain. Run where the "
        "keychain is reachable (a desktop session with an unlocked keyring, or a D-Bus Secret Service), or "
        "install a keyring backend (for example keyrings.alt) or set PYTHON_KEYRING_BACKEND."
    )


def explain_key_failure(exc: "BaseException | None") -> str:
    """
    One or two sentences on why the encryption key could not be used, and what to do about it.

    *exc* is what went wrong while fetching the key or decrypting with it. ``None`` means nothing went wrong
    but the data is still ciphertext, which is what ``storage.encrypt: false`` over encrypted files looks like.
    """
    if isinstance(exc, ImportError):
        return str(exc)  # _require_deps() already says which packages to install
    backend = keyring_backend_name()
    if is_unusable_backend(backend) or type(exc).__name__ == "NoKeyringError":
        return _no_backend_message(backend)
    if exc is None:
        return (
            "storage.encrypt is off in .cognirepo/config.json but this data is encrypted. Set storage.encrypt "
            "to true to read it (or restore the config you had)."
        )
    name = type(exc).__name__
    if name == "InvalidToken":
        return (
            "the key in this keychain does not decrypt this data: it was encrypted with a different key "
            "(another machine, user or keychain)."
        )
    if "Locked" in name:
        return "the OS keychain is locked: unlock it, then try again."
    return f"the encryption key could not be read from the OS keychain ({name}: {exc})."


def _require_deps():
    """Import and return (Fernet, keyring), raising a clear error if missing."""
    try:
        from cryptography.fernet import Fernet  # pylint: disable=import-outside-toplevel
        import keyring  # pylint: disable=import-outside-toplevel
        return Fernet, keyring
    except ImportError as exc:
        raise ImportError(
            "Encryption requires additional packages.\n"
            "  pipx (recommended):  pipx inject cognirepo keyring cryptography\n"
            "  venv/pip:            pip install 'cognirepo[security]'"
        ) from exc


def get_or_create_key(project_id: str) -> bytes:
    """
    Retrieve the Fernet encryption key for *project_id* from the OS keychain.
    If no key exists yet, generate one, persist it, and return it.
    The key is NEVER written to any file on disk.
    """
    fernet_cls, keyring = _require_deps()
    try:
        stored = keyring.get_password(SERVICE_NAME, project_id)
    except Exception as exc:  # pylint: disable=broad-except
        raise KeyUnavailableError(explain_key_failure(exc)) from exc
    if stored:
        return stored.encode()
    backend = keyring_backend_name()
    if backend and ".backends.null." in backend:
        # null.get_password() answers None and null.set_password() drops the key, so a key minted here is gone
        # at once: everything encrypted with it could never be read again.
        raise KeyUnavailableError(_no_backend_message(backend))
    key = fernet_cls.generate_key()
    try:
        keyring.set_password(SERVICE_NAME, project_id, key.decode())
    except Exception as exc:  # pylint: disable=broad-except
        raise KeyUnavailableError(explain_key_failure(exc)) from exc
    return key


def encrypt_bytes(data: bytes, key: bytes) -> bytes:
    """Encrypt *data* with the given Fernet *key*."""
    fernet_cls, _ = _require_deps()
    return fernet_cls(key).encrypt(data)


def decrypt_bytes(data: bytes, key: bytes) -> bytes:
    """Decrypt *data* with the given Fernet *key*."""
    fernet_cls, _ = _require_deps()
    return fernet_cls(key).decrypt(data)
