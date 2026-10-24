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
TYPES = ("tool.start", "tool.end", "tool.error", "tool.shed", "session.start", "session.end", "session.client",
         "watcher.reindex", "graph.delta", "prune", "service")

#: a session with no ``session.end`` is "active" this long after its last event, "stale" afterwards
#: (a crashed or SIGKILLed server never writes ``session.end``)
SESSION_ACTIVE_SECS = 600
_SESSION_LIST_MAX = 100
_CALLS_MAX = 500
SESSIONS_FILE = "sessions.json"
_SESSIONS_KEPT = 200
_PROC_START_TOLERANCE_SECS = 2.0


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


def read_matching(store_dir: str, types: tuple[str, ...] = (), limit: int = 100,
                  session: str | None = None) -> list[dict[str, Any]]:
    """The last ``limit`` events matching ``types`` (glob list, empty = all) and ``session``, oldest first.
    Reads the retained log (live file + one backup), so it is bounded by event-log retention."""
    from collections import deque  # pylint: disable=import-outside-toplevel
    out: "deque[dict[str, Any]]" = deque(maxlen=max(1, limit))
    for ev in _iter_all(store_dir):
        if matches(ev, session, types):
            out.append(ev)
    return list(out)


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


# ── sessions (#208): derived from the event log, no second store ─────────────

def _iter_all(store_dir: str) -> Iterator[dict[str, Any]]:
    """Every retained event, oldest first (backup file, then the live one)."""
    path = events_path(store_dir)
    yield from _iter_file(path + ".1")
    yield from _iter_file(path)


def _parse_ts(ts: str | None) -> float | None:
    try:
        return datetime.strptime(str(ts), "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def _sessions_path(store_dir: str) -> str:
    return os.path.join(events_dir(store_dir), SESSIONS_FILE)


def _load_sidecar(store_dir: str) -> dict[str, dict[str, Any]]:
    try:
        with open(_sessions_path(store_dir), encoding="utf-8") as fh:
            rows = json.load(fh)
        return {r["id"]: r for r in rows if isinstance(r, dict) and isinstance(r.get("id"), str)}
    except (OSError, ValueError, TypeError, KeyError):
        return {}


def record_session(store_dir: str, session_id: str, **fields: Any) -> None:
    """Upsert one row of ``events/sessions.json`` (merge: ``None`` values never overwrite).

    Called only when a session starts, learns its client, or ends — never per tool call — so a closed
    session outlives the event log's rotation. Best-effort and cross-process safe (the events lock);
    keeps the newest ``_SESSIONS_KEPT`` rows. Never raises.
    """
    if not enabled() or not session_id:
        return
    try:
        from filelock import FileLock, Timeout  # pylint: disable=import-outside-toplevel
        os.makedirs(events_dir(store_dir), exist_ok=True)
        try:
            with FileLock(os.path.join(events_dir(store_dir), "events.lock"), timeout=_LOCK_WAIT_SECS):
                rows = _load_sidecar(store_dir)
                row = rows.setdefault(session_id, {"id": session_id})
                row.update({k: v for k, v in fields.items() if v is not None})
                keep = sorted(rows.values(), key=lambda r: str(r.get("started", "")), reverse=True)[:_SESSIONS_KEPT]
                atomic_write(_sessions_path(store_dir), json.dumps(keep, separators=(",", ":")), fsync=False)
        except Timeout:
            pass
    except Exception:  # pylint: disable=broad-except
        pass


def _process_gone(pid: Any, proc_start: Any) -> bool:
    """True when the process that wrote a session is no longer there (or its pid was reused)."""
    if not isinstance(pid, int):
        return False
    from core.config import procutil  # pylint: disable=import-outside-toplevel
    if not procutil.pid_alive(pid):
        return True
    if isinstance(proc_start, (int, float)):
        try:
            import psutil  # pylint: disable=import-outside-toplevel
        except ImportError:
            return False
        try:
            return abs(psutil.Process(pid).create_time() - float(proc_start)) > _PROC_START_TOLERANCE_SECS
        except psutil.NoSuchProcess:
            return True
        except Exception:  # pylint: disable=broad-except   # AccessDenied etc.: cannot tell, assume alive
            return False
    return False


def list_sessions(store_dir: str, *, now: float | None = None, limit: int = _SESSION_LIST_MAX) -> list[dict[str, Any]]:
    """One row per ``session_id`` seen in ``tool.*`` / ``session.*`` events or in ``events/sessions.json``,
    most recently active first.

    The event log is bounded by retention (live file plus one backup, ~10 MiB), but ``sessions.json``
    keeps the last 200 sessions' start, client, pid and final call count, so a closed session survives
    rotation. ``client`` is the MCP ``clientInfo.name`` (known from the first ``tools/list``). ``state`` is
    ``closed`` (``session.end`` seen, or its process is gone — ``closed_by`` says which), ``active`` or ``stale``.
    """
    side = _load_sidecar(store_dir)
    by_id: dict[str, dict[str, Any]] = {}
    for ev in _iter_all(store_dir):
        sid, typ = ev.get("session_id"), str(ev.get("type", ""))
        if not sid or not typ.startswith(("tool.", "session.")):
            continue
        row = by_id.get(sid)
        if row is None:
            row = by_id[sid] = {"id": sid, "client": None, "started": ev["ts"], "last_activity": ev["ts"],
                                "call_count": 0, "closed_at": None, "pid": None, "proc_start": None}
        row["last_activity"] = ev["ts"]
        if ev.get("client") and not row["client"]:
            row["client"] = ev["client"]
        if typ == "session.start":
            if isinstance(ev.get("pid"), int):
                row["pid"] = ev["pid"]
            if isinstance(ev.get("proc_start"), (int, float)):
                row["proc_start"] = ev["proc_start"]
        if typ in ("tool.start", "tool.shed"):
            row["call_count"] += 1
        elif typ == "session.end":
            row["closed_at"] = ev["ts"]
    for sid, srow in side.items():           # fold in what the log no longer (or never) held
        row = by_id.get(sid)
        if row is None:
            row = by_id[sid] = {"id": sid, "client": None, "started": srow.get("started") or srow.get("last_activity") or "",
                                "last_activity": srow.get("last_activity") or srow.get("started") or "",
                                "call_count": 0, "closed_at": None, "pid": None, "proc_start": None}
        if srow.get("started") and srow["started"] < row["started"]:
            row["started"] = srow["started"]
        row["client"] = row["client"] or srow.get("client")
        row["pid"] = row["pid"] if row["pid"] is not None else srow.get("pid")
        row["proc_start"] = row["proc_start"] if row["proc_start"] is not None else srow.get("proc_start")
        row["closed_at"] = row["closed_at"] or srow.get("closed_at")
        if isinstance(srow.get("call_count"), int):
            row["call_count"] = max(row["call_count"], srow["call_count"])
        if srow.get("last_activity") and srow["last_activity"] > row["last_activity"]:
            row["last_activity"] = srow["last_activity"]
    t_now = time.time() if now is None else now
    for row in by_id.values():
        last = _parse_ts(row["last_activity"])
        row["closed_by"] = "session_end" if row["closed_at"] else None
        if not row["closed_at"] and _process_gone(row["pid"], row["proc_start"]):
            row["closed_at"], row["closed_by"] = row["last_activity"], "process_gone"
        row["state"] = ("closed" if row["closed_at"] else
                        "active" if last is not None and t_now - last <= SESSION_ACTIVE_SECS else "stale")
        row.pop("proc_start", None)
    rows = sorted(by_id.values(), key=lambda r: r["last_activity"], reverse=True)
    return rows[:max(0, limit)]


def session_calls(store_dir: str, session_id: str, limit: int = 100) -> list[dict[str, Any]] | None:
    """The last ``limit`` tool calls of a session, oldest first; ``None`` if the session is unknown.

    A call is one ``tool.start`` joined to its ``tool.end`` / ``tool.error`` by ``trace_id`` (``status``
    is ``running`` until one arrives); a ``tool.shed`` is a call that never started.
    """
    calls: dict[Any, dict[str, Any]] = {}
    order: list[Any] = []
    known = False
    for ev in _iter_all(store_dir):
        if ev.get("session_id") != session_id:
            continue
        known = True
        typ = str(ev.get("type", ""))
        if typ == "tool.start":
            key = ev.get("trace_id") or ("seq", ev["seq"])
            calls[key] = {"trace_id": ev.get("trace_id"), "tool": ev.get("tool"), "started": ev["ts"],
                          "dur_ms": None, "status": "running", "args_summary": ev.get("args_summary"),
                          "result_summary": None}
            order.append(key)
        elif typ in ("tool.end", "tool.error"):
            rec = calls.get(ev.get("trace_id"))
            if rec is not None:
                rec["dur_ms"] = ev.get("dur_ms")
                rec["status"] = "ok" if typ == "tool.end" else "error"
                rec["result_summary"] = ev.get("result_summary") or ev.get("error")
        elif typ == "tool.shed":
            key = ("seq", ev["seq"])
            calls[key] = {"trace_id": ev.get("trace_id"), "tool": ev.get("tool"), "started": ev["ts"],
                          "dur_ms": None, "status": "shed", "args_summary": None,
                          "result_summary": ev.get("reason")}
            order.append(key)
    if not known:
        return None
    return [calls[k] for k in order][-max(0, min(limit, _CALLS_MAX)):]
