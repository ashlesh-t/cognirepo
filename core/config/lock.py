# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Cross-process file lock for CogniRepo storage writes.

Multiple AI agents (Claude, Gemini, Cursor) each run their own MCP server
process but share the same .cognirepo/ directory on disk.  Without a lock,
concurrent store_memory() or graph.save() calls from two processes can
interleave and corrupt FAISS index or JSON metadata files.

Usage:
    from config.lock import store_lock

    with store_lock():
        faiss.write_index(idx, path)
        _save_meta()
"""

import logging
import os
import threading
import time

from core.config.paths import get_path

try:
    from filelock import Timeout as _BaseTimeout
except ImportError:  # store_lock() raises a clearer ImportError itself
    _BaseTimeout = RuntimeError

_log = logging.getLogger(__name__)

#: ``filelock.Timeout`` (or a stand-in when filelock is missing): what MCP tools and the CLI catch so a
#: lock timeout from ANY lock — ours or a raw FileLock — is reported as "store busy", not a traceback.
LockTimeout = _BaseTimeout


def busy_message(exc: BaseException) -> str:
    """User-facing text for any lock timeout (StoreBusy already has it; a raw Timeout gets the same shape)."""
    if isinstance(exc, StoreBusy):
        return str(exc)
    where = getattr(exc, "lock_file", "") or "a store lock"
    return (f"the CogniRepo store is busy: another process is holding {where}. "
            "Nothing was changed - retry in a moment.")

_LOCK_FILENAME = "cognirepo.lock"

#: a lock held longer than this is logged (WARNING) when released — long holds are what make other
#: processes time out (COGNIREPO-141). Override with COGNIREPO_LOCK_HOLD_WARN_SECS.
_HOLD_WARN_SECS = 10.0


class StoreBusy(_BaseTimeout):
    """Another process (or thread) held a store lock for longer than the caller was willing to wait.

    A ``filelock.Timeout`` subclass, so existing ``except Timeout`` code keeps working, but with the
    lock file and the wait in the message and as attributes. It is a *retryable* condition, not data
    loss: nothing was written under the lock that could not be acquired. MCP tools turn it into a
    structured ``{"error": …, "busy": True, "retryable": True}`` result and the CLI exits with 75
    (EX_TEMPFAIL) instead of a traceback.
    """

    def __init__(self, lock_path: str, timeout: float) -> None:
        try:
            super().__init__(lock_path)
        except TypeError:  # RuntimeError fallback when filelock is missing
            RuntimeError.__init__(self, lock_path)
        self.lock_path = lock_path
        self.timeout = timeout

    def __str__(self) -> str:
        return (f"the CogniRepo store is busy: another process has held {self.lock_path} for more than "
                f"{self.timeout:g}s. Nothing was changed - retry in a moment.")

# Per-thread record of the lock files this thread currently holds: {path: [depth, FileLock, t_acquired]}.
# filelock re-entrancy is per *instance*, and store_lock() builds a new instance per call, so a
# nested `with store_lock():` used to block 15 s on its own file descriptor and then raise
# (COGNIREPO-141). Different threads still exclude each other — they hold different fds.
_HELD = threading.local()


def _held() -> dict:
    if not hasattr(_HELD, "locks"):
        _HELD.locks = {}
    return _HELD.locks


def _hold_warn_secs() -> float:
    try:
        return float(os.environ.get("COGNIREPO_LOCK_HOLD_WARN_SECS", _HOLD_WARN_SECS))
    except ValueError:
        return _HOLD_WARN_SECS


class LockOrderError(RuntimeError):
    """A thread tried to take a second, different store lock while holding one (strict mode only)."""


_NESTING_SEEN: set = set()


def _check_order(held: dict, new_path: str) -> None:
    """Different store locks must not be nested (docs/architecture/GRAPH_CONCURRENCY.md, "Lock order").

    Re-entering the SAME lock is fine and handled by the depth counter. Taking a different one while
    holding another is what could build a lock cycle between processes, so it is logged once per pair
    and, with ``COGNIREPO_LOCK_STRICT=1`` (used by the test suite's lock-order test), raises.
    """
    others = [p for p in held if p != new_path]
    if not others:
        return
    pair = (others[0], new_path)
    if os.environ.get("COGNIREPO_LOCK_STRICT"):
        raise LockOrderError(f"acquiring {new_path} while holding {others[0]}: store locks must not nest")
    if pair not in _NESTING_SEEN:
        _NESTING_SEEN.add(pair)
        _log.warning("store lock %s taken while holding %s - nested store locks risk a cross-process "
                     "deadlock; see docs/architecture/GRAPH_CONCURRENCY.md (Lock order)", new_path, others[0])


class _ReentrantStoreLock:
    """Context manager over a cross-process FileLock that the *same thread* may re-enter.

    The first ``with`` acquires the OS lock; nested ones (e.g. ``save()`` calling a helper that
    also locks) only bump a depth counter, and the OS lock is released when the outermost one
    exits. Only the SAME lock path re-enters — never nest two different locks (documented order:
    graph → ast → vector → episodic → behaviour; see docs/architecture/GRAPH_CONCURRENCY.md).
    """

    def __init__(self, lock_path: str, timeout: float) -> None:
        self._path = os.path.abspath(lock_path)
        self._timeout = timeout

    def acquire(self, timeout: "float | None" = None) -> "_ReentrantStoreLock":
        held = _held()
        entry = held.get(self._path)
        if entry is not None:
            entry[0] += 1
            return self
        from filelock import FileLock, Timeout  # pylint: disable=import-outside-toplevel
        wait = self._timeout if timeout is None else timeout
        _check_order(held, self._path)
        lock = FileLock(self._path, timeout=wait)
        try:
            lock.acquire()  # raises filelock.Timeout; nothing is registered on failure
        except Timeout as exc:
            raise StoreBusy(self._path, wait) from exc
        held[self._path] = [1, lock, time.monotonic()]
        return self

    def release(self) -> None:
        held = _held()
        entry = held.get(self._path)
        if entry is None:
            return
        entry[0] -= 1
        if entry[0] <= 0:
            del held[self._path]
            held_for = time.monotonic() - entry[2]
            entry[1].release()
            if held_for > _hold_warn_secs():
                _log.warning("store lock %s was held for %.1fs - other processes wait this long "
                             "(and time out after their own limit)", self._path, held_for)

    def __enter__(self) -> "_ReentrantStoreLock":
        return self.acquire()

    def __exit__(self, *_exc) -> None:
        self.release()


def store_lock(timeout: float = 15.0, lock_path: "str | None" = None):
    """
    Return a re-entrant cross-process lock on .cognirepo/cognirepo.lock.

    timeout    — seconds to wait before raising filelock.Timeout (default 15 s).
    lock_path  — lock a different file (e.g. a store that lives outside the repo, such as the
                 global learnings, so repos don't serialize on — or miss — each other's lock).
    Re-entrant for the same thread (see _ReentrantStoreLock). Raises ImportError if filelock is
    not installed — concurrent write safety requires filelock; run: pip install filelock
    """
    try:
        import filelock  # pylint: disable=import-outside-toplevel,unused-import
    except ImportError as exc:
        raise ImportError(
            "filelock is required for concurrent write safety. "
            "Run: pip install filelock"
        ) from exc
    return _ReentrantStoreLock(lock_path or get_path(_LOCK_FILENAME), timeout)
