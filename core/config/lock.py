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

import os
import threading

from core.config.paths import get_path

_LOCK_FILENAME = "cognirepo.lock"

# Per-thread record of the lock files this thread currently holds: {path: [depth, FileLock]}.
# filelock re-entrancy is per *instance*, and store_lock() builds a new instance per call, so a
# nested `with store_lock():` used to block 15 s on its own file descriptor and then raise
# (COGNIREPO-141). Different threads still exclude each other — they hold different fds.
_HELD = threading.local()


def _held() -> dict:
    if not hasattr(_HELD, "locks"):
        _HELD.locks = {}
    return _HELD.locks


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
        from filelock import FileLock  # pylint: disable=import-outside-toplevel
        lock = FileLock(self._path, timeout=self._timeout if timeout is None else timeout)
        lock.acquire()  # raises filelock.Timeout; nothing is registered on failure
        held[self._path] = [1, lock]
        return self

    def release(self) -> None:
        held = _held()
        entry = held.get(self._path)
        if entry is None:
            return
        entry[0] -= 1
        if entry[0] <= 0:
            del held[self._path]
            entry[1].release()

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
