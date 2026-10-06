# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Side-effect-free reads and writer-only quarantine for on-disk stores (COGNIREPO-135).

Several processes share ``.cognirepo/``. A *reader* that meets an unreadable file must not
act on that belief: renaming the file aside, sweeping scratch files, or returning an empty
value that the next write persists all destroy good data when the "corruption" was just a
concurrent writer or a missing decryption key.

Rules encoded here:

* **Readers never mutate.** :func:`read_retry` retries with a short backoff (a transient
  failure heals itself) and then raises :class:`StoreUnreadableError` — it never renames,
  deletes or writes anything.
* **Ciphertext we cannot decrypt is "locked", not "corrupt"** (:func:`looks_encrypted`): it is
  never quarantined, because a missing keyring would otherwise destroy a healthy store.
* **Only a writer may quarantine, and only when the damage is stable.**
  :func:`quarantine_if_stably_corrupt` renames a file aside (never deletes it) after it has
  stayed unreadable *and unchanged* across two checks. The caller should hold
  ``core.config.lock.store_lock()`` (not taken here: the lock is not re-entrant, see #141).
* **An unreadable load is never followed by a save of the empty value** — callers either raise
  or refuse to save until the store is readable or has been quarantined by a writer.
"""
import logging
import os
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

_FERNET_PREFIX = b"gAAAAA"  # every Fernet token starts with version byte 0x80, base64'd

__all__ = [
    "StoreUnreadableError", "looks_encrypted", "read_retry", "quarantine_if_stably_corrupt",
]


class StoreUnreadableError(RuntimeError):
    """A store file could not be read; it has NOT been modified in any way."""

    def __init__(self, path: str, reason: str, *, locked: bool = False) -> None:
        self.path = path
        self.reason = reason
        self.locked = locked
        hint = (
            "it is encrypted and cannot be decrypted here (install keyring/cryptography or "
            "restore the key)" if locked else
            "it is left untouched; a writer quarantines it only if it stays unreadable"
        )
        super().__init__(f"{path} is unreadable ({reason}); {hint}.")


def looks_encrypted(raw: bytes) -> bool:
    """True if ``raw`` is a Fernet token (ciphertext we failed to decrypt, not corruption)."""
    return raw.lstrip()[:6] == _FERNET_PREFIX


def read_retry(
    path: str, load: Callable[[], Any], *, attempts: int = 3, delay: float = 0.05,
    retry_on: tuple = (ValueError, OSError),
) -> Any:
    """Call ``load()`` (which re-reads the file each time), retrying transient failures.

    ``FileNotFoundError`` propagates immediately (absent is a normal state). After ``attempts``
    failures raises :class:`StoreUnreadableError` chained to the last error. Never writes.
    A ``StoreUnreadableError`` raised by ``load`` itself (e.g. locked ciphertext) is final.
    """
    last: Exception | None = None
    for i in range(max(1, attempts)):
        try:
            return load()
        except FileNotFoundError:
            raise
        except StoreUnreadableError:
            raise
        except retry_on as exc:  # JSONDecodeError and UnicodeDecodeError are ValueErrors
            last = exc
            if i + 1 < attempts:
                time.sleep(delay * (2 ** i))
    raise StoreUnreadableError(path, f"{type(last).__name__}: {last}") from last


def _stat_key(path: str) -> "tuple[int, int] | None":
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def quarantine_if_stably_corrupt(
    path: str, is_readable: Callable[[], bool], *, settle: float = 0.15,
) -> "str | None":
    """Writer-side: move an unreadable file aside, but only if the damage is stable.

    Returns the quarantine path, or ``None`` if the file is readable, absent, still changing
    (a concurrent writer may be mid-rewrite) or the rename failed. The original bytes are kept
    in ``<path>.corrupt-<unix_ts>`` — nothing is ever deleted. Call under ``store_lock()``.
    """
    if is_readable():
        return None
    first = _stat_key(path)
    if first is None:
        return None
    time.sleep(settle)
    if _stat_key(path) != first or is_readable():
        return None  # it moved or healed under us: not corrupt, leave it alone
    dest = f"{path}.corrupt-{int(time.time())}"
    try:
        os.replace(path, dest)
    except OSError as exc:
        logger.warning("could not quarantine %s: %s", path, exc)
        return None
    logger.warning("quarantined unreadable %s -> %s", path, dest)
    return dest
