# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Server-sent events over ``core.events`` for ``GET /api/v1/events`` (#207)."""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

from core import events

MAX_STREAMS = 8                 # each open stream holds a poll loop; the console needs one or two
POLL_SECS = 0.5
HEARTBEAT_SECS = 15.0
RETRY_MS = 3000
BACKLOG_LIMIT = 1000


def parse_last_event_id(raw: str | None) -> int | None:
    try:
        n = int((raw or "").strip())
    except ValueError:
        return None
    return n if n >= 0 else None


def format_event(ev: dict[str, Any]) -> str:
    # ``id:`` is the seq, so the browser's automatic ``Last-Event-ID`` on reconnect resumes exactly here.
    return f"id: {ev['seq']}\nevent: {ev.get('type', 'message')}\ndata: {json.dumps(ev, separators=(',', ':'))}\n\n"


async def stream(is_disconnected, store_dir: str, *, after: int | None = None, replay: int = 0,
                 session: str | None = None, types: tuple[str, ...] = (),
                 counter: dict[str, int] | None = None) -> AsyncIterator[str]:
    """Yield SSE frames until the client goes away.

    ``after`` (Last-Event-ID) resumes from that seq; otherwise ``replay`` sends the last N events, and
    with neither only new events are sent. The tailer is positioned BEFORE the backlog is read so an
    event written in between shows up in both — ``seen`` drops the duplicate.
    """
    counter = counter if counter is not None else {"n": 0}
    counter["n"] += 1
    try:
        yield f"retry: {RETRY_MS}\n\n"
        tailer = events.Tailer(store_dir)
        if after is not None:
            backlog = await asyncio.to_thread(events.read_since, store_dir, after, BACKLOG_LIMIT)
        elif replay:
            backlog = await asyncio.to_thread(events.read_last, store_dir, replay)
        else:
            backlog = []
        seen = after if after is not None else 0
        for ev in backlog:
            seen = max(seen, ev["seq"])
            if events.matches(ev, session, types):
                yield format_event(ev)
        last_beat = time.monotonic()
        while not await is_disconnected():
            for ev in await asyncio.to_thread(tailer.poll):
                if ev["seq"] <= seen:
                    continue
                seen = ev["seq"]
                if events.matches(ev, session, types):
                    yield format_event(ev)
                    last_beat = time.monotonic()
            if time.monotonic() - last_beat >= HEARTBEAT_SECS:
                yield ": heartbeat\n\n"
                last_beat = time.monotonic()
            await asyncio.sleep(POLL_SECS)
    finally:
        counter["n"] -= 1
