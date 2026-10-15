# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Live event log for the Engram console (#207): ``<store>/events/events.jsonl``.

Every CogniRepo process that does something worth watching (an MCP tool call, a watcher re-index,
a UI service action) appends one JSON line. The control API tails the file and pushes it to the
console over SSE (``GET /api/v1/events``), so the UI process stays read-only towards the index and
needs no cross-process transport beyond this file — the same pattern as ``ui/audit.log``.

Guarantees
  * ``emit()`` never raises and never blocks a caller for more than ``_LOCK_WAIT_SECS``: telemetry
    must not be able to fail or stall a tool call. A dropped event is simply dropped.
  * ``seq`` is strictly increasing across processes (assigned under a file lock, persisted in a
    sidecar so it survives rotation) — it doubles as the SSE ``id:`` for ``Last-Event-ID`` resume.
  * The file is mode 0600 and size-rotated (one backup, ``events.jsonl.1``).
  * Summaries are length-capped and secret-named fields are dropped (``core.redact``). Free text an
    agent put in a query cannot be scrubbed — set ``COGNIREPO_EVENTS_METADATA_ONLY=1`` to omit
    ``args_summary`` / ``result_summary`` entirely, or ``COGNIREPO_EVENTS=0`` to write nothing.
"""
from __future__ import annotations

import fnmatch
import json
import logging
import os
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

from core.config.atomic import atomic_write
from core.redact import drop_secrets

_log = logging.getLogger(__name__)

EVENTS_DIR = "events"
EVENTS_FILE = "events.jsonl"
MAX_BYTES = 5 * 1024 * 1024
_LOCK_WAIT_SECS = 0.25
_SUMMARY_MAX = 200
_LIST_MAX = 50          # nodes / edges / file lists per event: keeps one line well under PIPE_BUF-ish sizes
_SUMMARY_FIELDS = ("args_summary", "result_summary")

#: every event carries these; the rest is type-specific (see docs/UI_API.md)
TYPES = ("tool.start", "tool.end", "tool.error", "tool.shed", "watcher.reindex", "graph.delta", "prune", "service")


def enabled() -> bool:
    return os.environ.get("COGNIREPO_EVENTS", "1").strip().lower() not in ("0", "false", "off", "no")


def metadata_only() -> bool:
    return os.environ.get("COGNIREPO_EVENTS_METADATA_ONLY", "").strip().lower() in ("1", "true", "on", "yes")


def events_dir(store_dir: str) -> str:
    return os.path.join(store_dir, EVENTS_DIR)


def events_path(store_dir: str) -> str:
    return os.path.join(events_dir(store_dir), EVENTS_FILE)


def clip(text: Any, limit: int = _SUMMARY_MAX) -> str:
    s = " ".join(str(text).split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def summarize_args(kwargs: dict[str, Any]) -> str:
    """``key=value`` pairs with secret-named keys dropped, each value clipped, the whole clipped to 200."""
    parts = [f"{k}={clip(v, 60)}" for k, v in drop_secrets(kwargs).items() if v not in (None, "")]
    return clip(", ".join(parts))


def _default_store() -> str:
    from core.config.paths import get_cognirepo_dir  # pylint: disable=import-outside-toplevel
    return str(get_cognirepo_dir())


def _last_seq_from_file(path: str) -> int:
    """Recover the counter when the sidecar is missing: the last parsable record's seq."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 8192))
            for line in reversed(fh.read().splitlines()):
                try:
                    return int(json.loads(line)["seq"])
                except (ValueError, KeyError, TypeError):
                    continue
    except OSError:
        pass
    return 0


def emit(type: str, *, store_dir: str | None = None, **fields: Any) -> int | None:  # pylint: disable=redefined-builtin
    """Append one event; return its ``seq`` or ``None`` if it was dropped. Never raises."""
    if not enabled():
        return None
    try:
        return _emit(type, store_dir or _default_store(), fields)
    except Exception as exc:  # pylint: disable=broad-except
        _log.debug("event %s dropped: %s", type, exc)
        return None


def _emit(type_: str, store_dir: str, fields: dict[str, Any]) -> int | None:
    from filelock import FileLock, Timeout  # pylint: disable=import-outside-toplevel

    d = events_dir(store_dir)
    os.makedirs(d, exist_ok=True)
    path = events_path(store_dir)
    seq_path = os.path.join(d, "events.seq")

    body = drop_secrets(fields)
    if metadata_only():
        for k in _SUMMARY_FIELDS:
            body.pop(k, None)
    for k in _SUMMARY_FIELDS:
        if k in body:
            body[k] = clip(body[k])
    for k in ("nodes", "edges", "reindexed", "removed"):
        if isinstance(body.get(k), list) and len(body[k]) > _LIST_MAX:
            body[k] = body[k][:_LIST_MAX]
            body[f"{k}_truncated"] = True

    lock = FileLock(os.path.join(d, "events.lock"), timeout=_LOCK_WAIT_SECS)
    try:
        with lock:
            try:
                with open(seq_path, encoding="ascii") as fh:
                    seq = int(fh.read().strip() or 0)
            except (OSError, ValueError):
                seq = _last_seq_from_file(path)
            seq += 1
            record = {"seq": seq, "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                      "type": type_, **body}
            line = (json.dumps(record, default=str, separators=(",", ":")) + "\n").encode("utf-8")
            try:
                if os.path.getsize(path) + len(line) > MAX_BYTES:
                    os.replace(path, path + ".1")
            except OSError:
                pass
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, line)
            finally:
                os.close(fd)
            atomic_write(seq_path, str(seq), fsync=False)   # status counter, not a store
            return seq
    except Timeout:
        return None


# ── reading ──────────────────────────────────────────────────────────────────

def matches(event: dict[str, Any], session: str | None = None, types: tuple[str, ...] = ()) -> bool:
    """Filter used by the SSE endpoint: exact ``session_id``, and ``types`` as globs (``tool.*``)."""
    if session and event.get("session_id") != session:
        return False
    return not types or any(fnmatch.fnmatchcase(str(event.get("type", "")), t) for t in types)


def parse_types(raw: str | None) -> tuple[str, ...]:
    return tuple(t.strip() for t in (raw or "").split(",") if t.strip())[:16]


def _iter_file(path: str) -> Iterator[dict[str, Any]]:
    try:
        with open(path, "rb") as fh:
            for raw in fh:
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(ev, dict) and isinstance(ev.get("seq"), int):
                    yield ev
    except OSError:
        return


def read_since(store_dir: str, after_seq: int, limit: int = 1000) -> list[dict[str, Any]]:
    """Events with ``seq > after_seq`` in order (backup file first), at most ``limit`` — the first ones."""
    path = events_path(store_dir)
    out: list[dict[str, Any]] = []
    for p in (path + ".1", path):
        for ev in _iter_file(p):
            if ev["seq"] > after_seq:
                out.append(ev)
                if len(out) >= limit:
                    return out
    return out


def read_last(store_dir: str, n: int) -> list[dict[str, Any]]:
    """The last ``n`` events (for ``?replay=``)."""
    path = events_path(store_dir)
    evs = list(_iter_file(path))
    if len(evs) < n:
        evs = list(_iter_file(path + ".1")) + evs
    return evs[-n:] if n > 0 else []


def last_seq(store_dir: str) -> int:
    try:
        with open(os.path.join(events_dir(store_dir), "events.seq"), encoding="ascii") as fh:
            return int(fh.read().strip() or 0)
    except (OSError, ValueError):
        return _last_seq_from_file(events_path(store_dir))


class Tailer:
    """Follow the live file from where it is now; survives rotation. ``poll()`` returns new events."""

    def __init__(self, store_dir: str) -> None:
        self.path = events_path(store_dir)
        self._ino, self._offset = self._stat()
        self._buf = b""

    def _stat(self) -> tuple[int | None, int]:
        try:
            st = os.stat(self.path)
            return st.st_ino, st.st_size
        except OSError:
            return None, 0

    def _read_from(self, path: str, offset: int) -> tuple[list[dict[str, Any]], int]:
        out: list[dict[str, Any]] = []
        try:
            with open(path, "rb") as fh:
                fh.seek(offset)
                data = self._buf + fh.read()
                self._buf = b""
        except OSError:
            return out, offset
        end = data.rfind(b"\n") + 1
        self._buf = data[end:]                 # a partial last line waits for its newline
        for raw in data[:end].splitlines():
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            if isinstance(ev, dict) and isinstance(ev.get("seq"), int):
                out.append(ev)
        return out, offset + len(data)

    def poll(self) -> list[dict[str, Any]]:
        ino, size = self._stat()
        out: list[dict[str, Any]] = []
        if self._ino is not None and ino != self._ino:
            # rotated: finish what we had not read of the old file (now ``.1``), then start the new one
            old, _ = self._read_from(self.path + ".1", self._offset)
            out.extend(old)
            self._buf, self._offset = b"", 0
        self._ino = ino
        if ino is not None and size > self._offset:
            new, self._offset = self._read_from(self.path, self._offset)
            out.extend(new)
        return out
