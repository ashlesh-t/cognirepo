# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Append-only on-disk journal for KnowledgeGraph mutations (COGNIREPO-109).

Layout   : .cognirepo/graph/graph.journal — a sequence of records
               [4B big-endian payload length][4B big-endian crc32(payload)][payload]
           payload = pickle.dumps((seq, ops)), Fernet-encrypted per record when
           storage.encrypt is on (Fernet is not a streaming cipher, so the buffering
           granularity is one segment, not the whole graph).
Recovery : a short or crc-failing tail record is a torn write — everything before it
           is kept, the tail is reported so the caller can truncate it.
           A record that fails to *decrypt* is NOT a torn write; JournalUnreadable
           is raised so the caller refuses to discard the file.
"""
import os
import pickle
import struct
import zlib
from typing import Any, Iterator

_HEADER = struct.Struct(">II")

Op = tuple[Any, ...]


class JournalUnreadable(RuntimeError):
    """A journal record could not be decrypted/unpickled; the file must be preserved."""


def append_segment(path: str, seq: int, ops: list[Op], key: bytes | None) -> None:
    """Append one segment (``ops`` under sequence number ``seq``) and fsync it."""
    payload = pickle.dumps((seq, ops), protocol=pickle.HIGHEST_PROTOCOL)
    if key is not None:
        from core.security.encryption import encrypt_bytes  # pylint: disable=import-outside-toplevel
        payload = encrypt_bytes(payload, key)
    record = _HEADER.pack(len(payload), zlib.crc32(payload) & 0xFFFFFFFF) + payload
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "ab") as f:
        f.write(record)
        f.flush()
        os.fsync(f.fileno())


def iter_segments(
    path: str, key: bytes | None, start: int = 0,
) -> Iterator[tuple[int, list[Op], int]]:
    """Stream ``(seq, ops, end_offset)`` one segment at a time from byte ``start``.

    Memory is bounded by a single segment — callers apply ops as they arrive instead of
    holding the whole journal unpickled next to the graph. ``end_offset`` is absolute.
    A torn tail ends the stream quietly; mid-file damage raises JournalUnreadable.
    """
    for payload, offset, end in _frames(path, start):
        try:
            seq, ops = _decode(payload, key)
        except Exception as exc:  # pylint: disable=broad-except
            raise JournalUnreadable(f"{path}: record at offset {offset}: {exc}") from exc
        yield seq, ops, end


def boundary_end(path: str, start: int = 0) -> tuple[int, int]:
    """Return ``(good_end, file_size)`` using only length + crc — no decrypt, no unpickle.

    Cheap enough for the single writer to find where to append after a crash, even on a
    large journal. ``good_end < file_size`` means a torn tail starts at ``good_end``.
    """
    good_end = start
    for _payload, _offset, end in _frames(path, start, keep_payload=False):
        good_end = end
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    return good_end, size


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
) -> Iterator[tuple[bytes, int, int]]:
    """Yield ``(payload, start_offset, end_offset)`` for each intact frame (crc-verified)."""
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
            length, crc = _HEADER.unpack(header)
            payload = f.read(length)
            if len(payload) < length:
                return  # torn tail: an append cut short can only be the last record
            if (zlib.crc32(payload) & 0xFFFFFFFF) != crc:
                if f.read(1):
                    # Intact-length record with a bad crc and MORE data after it is not
                    # a torn append — it is damage mid-file. Refuse rather than silently
                    # drop (and later truncate away) the valid segments that follow.
                    raise JournalUnreadable(f"{path}: crc mismatch at offset {offset}")
                return  # bad record at the very end: treat as a torn tail
            end = offset + _HEADER.size + length
            yield (payload if keep_payload else b""), offset, end
            offset = end
