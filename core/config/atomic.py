# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Atomic file writes for every on-disk CogniRepo store (COGNIREPO-134).

Several processes (watcher, ``serve`` per agent, CLI) share ``.cognirepo/``. A plain
``open(path, "w")`` truncates the live file first, so a concurrent reader — or a crash —
sees an empty or half-written store, and callers that treat "unreadable" as "corrupt"
then act on it (#135). Writing to a unique scratch file in the same directory and
promoting it with ``os.replace`` makes the swap indivisible: readers see either the
complete old file or the complete new one, and a writer killed mid-write leaves the old
file untouched.

Recipe (the same one KnowledgeGraph.save uses for graph.pkl):
    mkstemp in the destination dir → write → flush + fsync → os.replace → fsync(dir)

The scratch name is unique per writer (mkstemp), so two concurrent writers never share or
truncate each other's tmp file (COGNIREPO-D13). Callers that need a *group* of files to
be mutually consistent must still hold ``core.config.lock.store_lock()``.
"""
import contextlib
import json
import os
import tempfile
from typing import Any, Callable, Iterator

__all__ = [
    "atomic_write", "atomic_write_with", "atomic_json_dump", "atomic_path",
]

_DEFAULT_MODE = 0o644  # what open(path, "w") gave under the usual 022 umask


def _fsync_dir(directory: str) -> None:
    """Persist the rename itself (POSIX); a no-op where directories can't be opened."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _target_mode(path: str) -> int:
    try:
        return os.stat(path).st_mode & 0o7777
    except OSError:
        return _DEFAULT_MODE


@contextlib.contextmanager
def atomic_path(path: str, *, fsync: bool = True) -> Iterator[str]:
    """Yield a scratch path to write to; promote it over ``path`` on clean exit.

    For writers that take a *filename* (``faiss.write_index``) rather than a file object.
    On any exception the scratch file is removed and ``path`` is left exactly as it was.
    """
    path = os.fspath(path)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=os.path.basename(path) + ".", suffix=".tmp")
    os.close(fd)
    try:
        yield tmp
        if fsync:
            with open(tmp, "rb") as f:
                os.fsync(f.fileno())
        os.chmod(tmp, _target_mode(path))
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    if fsync:
        _fsync_dir(directory)


def atomic_write_with(
    path: str, writer: Callable[[Any], None], *, binary: bool = False,
    encoding: str = "utf-8", fsync: bool = True,
) -> None:
    """Atomically replace ``path`` with whatever ``writer(file_object)`` writes."""
    with atomic_path(path, fsync=False) as tmp:
        kwargs = {} if binary else {"encoding": encoding}
        with open(tmp, "wb" if binary else "w", **kwargs) as f:  # scratch file, not the target
            writer(f)
            f.flush()
            if fsync:
                os.fsync(f.fileno())
    if fsync:
        _fsync_dir(os.path.dirname(os.fspath(path)) or ".")


def atomic_write(path: str, data: "bytes | str", *, encoding: str = "utf-8", fsync: bool = True) -> None:
    """Atomically replace ``path`` with ``data`` (bytes, or str encoded with ``encoding``).

    Encrypt before calling (``encrypt_bytes`` → ``atomic_write``): the helper never sees keys.
    """
    binary = isinstance(data, (bytes, bytearray, memoryview))
    atomic_write_with(path, lambda f: f.write(data), binary=binary, encoding=encoding, fsync=fsync)


def atomic_json_dump(path: str, obj: Any, *, indent: "int | None" = 2, fsync: bool = True, **dump_kwargs: Any) -> None:
    """``json.dump`` to ``path`` atomically."""
    atomic_write_with(path, lambda f: json.dump(obj, f, indent=indent, **dump_kwargs), fsync=fsync)
