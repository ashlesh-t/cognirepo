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

from config.paths import get_path

_LOCK_FILENAME = "cognirepo.lock"


def store_lock(timeout: float = 15.0):
    """
    Return a FileLock on .cognirepo/cognirepo.lock.

    timeout — seconds to wait before raising Timeout (default 15 s).
    Raises ImportError if filelock is not installed — concurrent write safety
    requires filelock; run: pip install filelock
    """
    try:
        from filelock import FileLock  # pylint: disable=import-outside-toplevel
        lock_path = get_path(_LOCK_FILENAME)
        return FileLock(lock_path, timeout=timeout)
    except ImportError as exc:
        raise ImportError(
            "filelock is required for concurrent write safety. "
            "Run: pip install filelock"
        ) from exc
