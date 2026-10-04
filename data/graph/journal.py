# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Append-only on-disk journal for KnowledgeGraph mutations (COGNIREPO-109).

Layout   : .cognirepo/graph/graph.journal — a sequence of records
               [4B length][4B crc32(seq || payload)][8B seq][payload]   (big-endian)
           payload = pickle.dumps((seq, ops)), Fernet-encrypted per record when
           storage.encrypt is on (Fernet is not a streaming cipher, so the buffering
           granularity is one segment, not the whole graph). The seq lives in the header
           too, so the next sequence number is read from the file tail by a
           length+crc-only scan — no decrypt, no unpickle (as Postgres/SQLite allocate
           the next log position from the on-disk tail, not from process memory).
Writers  : one at a time, enforced by WriterLease — an OS file lock held for the whole
           indexing run (the LevelDB/RocksDB LOCK, Lucene write.lock pattern). The OS drops
           it if the holder dies, so a crash never leaves a stale lease.
Recovery : a short or crc-failing tail record is a torn write — everything before it
           is kept, the tail is reported so the caller can truncate it.
           A record that fails to *decrypt* is NOT a torn write; JournalUnreadable
           is raised so the caller refuses to discard the file.
"""
import os
import pickle
import struct
import threading
import time
import zlib
from typing import Any, Iterator

_HEADER = struct.Struct(">IIQ")
_SEQ = struct.Struct(">Q")

Op = tuple[Any, ...]


class JournalUnreadable(RuntimeError):
    """A journal record could not be decrypted/unpickled; the file must be preserved."""


class JournalBusy(RuntimeError):
    """Another process already holds the graph writer lease."""

    def __init__(self, pid: int | None) -> None:
        self.pid = pid
        super().__init__(
            "indexing is already running"
            + (f" (pid {pid})" if pid else "")
            + " — it holds the knowledge-graph writer lease. Wait for it to finish, or set "
            "indexing.writer_wait_secs in config.json to queue behind it."
        )


_HELD_LOCK = threading.Lock()
_HELD: set[str] = set()  # lease paths held by THIS process — makes in-process exclusion
                         # independent of how a given filelock backend treats same-process locks


class WriterLease:
    """Exclusive, crash-safe right to journal the graph (one holder at a time).

    An OS advisory lock (filelock → flock/LockFileEx) on ``<journal>.writer``. The kernel
    releases it when the holder exits or is killed, so there is no stale-lease cleanup.
    The holder records its pid in a sidecar (``.writer.pid``) so a refused contender can say
    who owns it — not in the lock file itself, which filelock truncates on every attempt.
    """

    def __init__(self, journal_path: str) -> None:
        self._path = journal_path + ".writer"
        self._pid_path = self._path + ".pid"
        self._lock = None

    def _owner(self) -> int | None:
        try:
            with open(self._pid_path, encoding="utf-8") as f:
                return int(f.read().strip() or 0) or None
        except (OSError, ValueError):
            return None

    def acquire(self, wait: float = 0.0) -> None:
        """Take the lease or raise JournalBusy after waiting ``wait`` seconds."""
        from filelock import FileLock, Timeout  # pylint: disable=import-outside-toplevel
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        key = os.path.abspath(self._path)
        deadline = time.monotonic() + max(0.0, wait)
        while True:  # in-process holders first (deterministic), then the OS lock
            with _HELD_LOCK:
                if key not in _HELD:
                    _HELD.add(key)
                    break
            if time.monotonic() >= deadline:
                raise JournalBusy(os.getpid())
            time.sleep(0.05)
        lock = FileLock(self._path, thread_local=False)  # lease may be released from any thread
        try:
            lock.acquire(timeout=max(0.0, deadline - time.monotonic()))
        except Timeout as exc:
            with _HELD_LOCK:
                _HELD.discard(key)
            raise JournalBusy(self._owner()) from exc
        self._lock = lock
        try:
            with open(self._pid_path, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
        except OSError:
            pass  # advisory info only

    def release(self) -> None:
        if self._lock is not None:
            try:
                try:
                    os.unlink(self._pid_path)  # while still holding the lock: it is ours
                except OSError:
                    pass
                self._lock.release()
            finally:
                self._lock = None
                with _HELD_LOCK:
                    _HELD.discard(os.path.abspath(self._path))

    @property
    def held(self) -> bool:
        return self._lock is not None


def append_segment(path: str, seq: int, ops: list[Op], key: bytes | None) -> None:
    """Append one segment (``ops`` under sequence number ``seq``) and fsync it."""
    payload = pickle.dumps((seq, ops), protocol=pickle.HIGHEST_PROTOCOL)
    if key is not None:
        from core.security.encryption import encrypt_bytes  # pylint: disable=import-outside-toplevel
        payload = encrypt_bytes(payload, key)
    record = _HEADER.pack(len(payload), _crc(seq, payload), seq) + payload
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "ab") as f:
        f.write(record)
        f.flush()
        os.fsync(f.fileno())


def _crc(seq: int, payload: bytes) -> int:
    return zlib.crc32(payload, zlib.crc32(_SEQ.pack(seq))) & 0xFFFFFFFF


def iter_segments(
    path: str, key: bytes | None, start: int = 0,
) -> Iterator[tuple[int, list[Op], int]]:
    """Stream ``(seq, ops, end_offset)`` one segment at a time from byte ``start``.

    Memory is bounded by a single segment — callers apply ops as they arrive instead of
    holding the whole journal unpickled next to the graph. ``end_offset`` is absolute.
    A torn tail ends the stream quietly; mid-file damage raises JournalUnreadable.
    """
    for payload, hdr_seq, offset, end in _frames(path, start):
        try:
            seq, ops = _decode(payload, key)
            if seq != hdr_seq:
                raise ValueError(f"header seq {hdr_seq} != payload seq {seq}")
        except Exception as exc:  # pylint: disable=broad-except
            raise JournalUnreadable(f"{path}: record at offset {offset}: {exc}") from exc
        yield seq, ops, end


def boundary_end(path: str, start: int = 0) -> tuple[int, int, int]:
    """Return ``(good_end, file_size, last_seq)`` using only header + crc — no decrypt,
    no unpickle. ``last_seq`` is 0 when no intact record exists at/after ``start``.

    Cheap enough for a writer to find where to append and which sequence number comes
    next, even on a large journal. ``good_end < file_size`` means a torn tail starts at
    ``good_end``.
    """
    good_end, last_seq = start, 0
    for _payload, seq, _offset, end in _frames(path, start, keep_payload=False):
        good_end, last_seq = end, max(last_seq, seq)
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    return good_end, size, last_seq


def scan(
    path: str, key: bytes | None, start: int = 0,
) -> tuple[list[tuple[int, list[Op]]], int, int]:
    """Materialise the whole journal. Convenience for tests/diagnostics only — production
    replay streams through :func:`iter_segments`."""
    segments: list[tuple[int, list[Op]]] = []
    good_end = start
    for seq, ops, end in iter_segments(path, key, start):
        segments.append((seq, ops))
        good_end = end
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    return segments, good_end, size


def truncate_to(path: str, length: int) -> None:
    """Cut a torn tail off the journal."""
    with open(path, "r+b") as f:
        f.truncate(length)
        f.flush()
        os.fsync(f.fileno())


def _decode(payload: bytes, key: bytes | None) -> tuple[int, list[Op]]:
    data = payload
    if key is not None:
        from core.security.encryption import decrypt_bytes  # pylint: disable=import-outside-toplevel
        try:
            data = decrypt_bytes(payload, key)
        except Exception:  # pylint: disable=broad-except
            # written plaintext under a context that resolved encrypt=false — mirror the
            # graph.pkl fallback; a genuinely undecryptable record fails the unpickle.
            data = payload
    seq, ops = pickle.loads(data)  # nosec B301 — same trust boundary as graph.pkl (crc32 detects damage, not tampering; Fernet under storage.encrypt authenticates)
    return seq, ops


def _frames(
    path: str, start: int = 0, keep_payload: bool = True,
) -> Iterator[tuple[bytes, int, int, int]]:
    """Yield ``(payload, seq, start_offset, end_offset)`` per intact (crc-verified) frame."""
    try:
        f = open(path, "rb")  # pylint: disable=consider-using-with
    except FileNotFoundError:
        return
    with f:
        offset = start
        f.seek(start)
        while True:
            header = f.read(_HEADER.size)
            if len(header) < _HEADER.size:
                return  # clean EOF or torn header
            length, crc, seq = _HEADER.unpack(header)
            payload = f.read(length)
            if len(payload) < length:
                return  # torn tail: an append cut short can only be the last record
            if _crc(seq, payload) != crc:
                if f.read(1):
                    # Intact-length record with a bad crc and MORE data after it is not
                    # a torn append — it is damage mid-file. Refuse rather than silently
                    # drop (and later truncate away) the valid segments that follow.
                    raise JournalUnreadable(f"{path}: crc mismatch at offset {offset}")
                return  # bad record at the very end: treat as a torn tail
            end = offset + _HEADER.size + length
            yield (payload if keep_payload else b""), seq, offset, end
            offset = end
