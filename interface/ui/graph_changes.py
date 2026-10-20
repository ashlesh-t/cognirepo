# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""``GET /api/v1/graph/changes`` (#209): the knowledge graph's change feed, built from ``graph.delta`` events.

Read-only. ``graph_seq`` (``data.graph.graph_seq``) is the authority on how far the graph has moved;
the events carry the ops. Events are best-effort and rotate, so completeness is *proved*, not assumed:
every sequence number in ``(since, current]`` must have all ``parts`` of its batch (a batch is split into
``graph.delta`` events of at most ``MAX_BATCH_OPS`` ops; an event without ``part``/``parts`` is a whole batch),
each exactly once, none marked ``reset``. If any is missing (event dropped, rotated out, events disabled, a batch
over ``MAX_BATCH_TOTAL`` ops) or ambiguous (a part written twice) the answer is ``reset: true`` and the client
re-fetches ``GET /api/v1/graph``.
"""
from __future__ import annotations

from typing import Any

from core import events
from data.graph import graph_seq

MAX_SPAN = 100_000     # a client further behind than this re-fetches instead of replaying


def changes(store_dir: str, since: int, limit: int) -> dict[str, Any]:
    cur = graph_seq.read(store_dir)
    if since > cur:                       # store was rebuilt/reset under the client
        return {"seq": cur, "ops": [], "reset": True, "more": False}
    if since == cur:
        return {"seq": cur, "ops": [], "reset": False, "more": False}
    if cur - since > MAX_SPAN:
        return {"seq": cur, "ops": [], "reset": True, "more": False}

    # graph_seq -> {part number -> event}; a duplicated part is recorded as None (ambiguous)
    batches: dict[int, dict[int, Any]] = {}
    for ev in events._iter_all(store_dir):  # pylint: disable=protected-access
        gs = ev.get("graph_seq")
        if ev.get("type") == "graph.delta" and isinstance(gs, int) and since < gs <= cur:
            part = ev.get("part") if isinstance(ev.get("part"), int) else 1
            slot = batches.setdefault(gs, {})
            slot[part] = None if part in slot else ev
    reset = {"seq": cur, "ops": [], "reset": True, "more": False}
    ops: list[dict[str, Any]] = []
    last = since
    for gs in range(since + 1, cur + 1):
        slot = batches.get(gs)
        if not slot:
            return reset
        total = next((e.get("parts") for e in slot.values() if e and isinstance(e.get("parts"), int)), 1)
        if set(slot) != set(range(1, total + 1)):
            return reset
        batch: list[dict[str, Any]] = []
        for part in range(1, total + 1):
            ev = slot[part]
            if ev is None or ev.get("reset") or not isinstance(ev.get("ops"), list):
                return reset
            batch.extend(ev["ops"])
        if ops and len(ops) + len(batch) > limit:
            break
        ops.extend(batch)
        last = gs
    return {"seq": last, "ops": ops, "reset": False, "more": last < cur}
