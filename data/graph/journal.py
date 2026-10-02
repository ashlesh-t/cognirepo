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


def scan(
    path: str, key: bytes | None, start: int = 0,
) -> tuple[list[tuple[int, list[Op]]], int, int]:
    """Read the journal from byte offset ``start`` (a record boundary).

    Returns ``(segments, good_end, file_size)``; ``good_end`` is an absolute offset.
    ``good_end < file_size`` means a torn tail starts at ``good_end``.
    """
    segments: list[tuple[int, list[Op]]] = []
    good_end = start
    for seq, ops, end in _iter(path, key, start):
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


def _iter(path: str, key: bytes | None, start: int = 0) -> Iterator[tuple[int, list[Op], int]]:
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
            data = payload
            try:
                if key is not None:
                    from core.security.encryption import decrypt_bytes  # pylint: disable=import-outside-toplevel
                    data = decrypt_bytes(data, key)
                seq, ops = pickle.loads(data)  # nosec B301 — same trust boundary as graph.pkl (crc32 detects damage, not tampering; Fernet under storage.encrypt authenticates)
            except Exception as exc:  # pylint: disable=broad-except
                raise JournalUnreadable(f"{path}: record at offset {offset}: {exc}") from exc
            offset += _HEADER.size + length
            yield seq, ops, offset
