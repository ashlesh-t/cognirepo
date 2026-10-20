# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""``GET /api/v1/graph/changes`` (#209): the knowledge graph's change feed, built from ``graph.delta`` events.

Read-only. ``graph_seq`` (``data.graph.graph_seq``) is the authority on how far the graph has moved;
the events carry the ops. Events are best-effort and rotate, so completeness is *proved*, not assumed:
every sequence number in ``(since, current]`` must have exactly one non-reset ``graph.delta``. If any is
missing (event dropped, rotated out, events disabled, a bulk-index batch) the answer is ``reset: true``
and the client re-fetches ``GET /api/v1/graph``.
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

    batches: dict[int, dict[str, Any]] = {}
    for ev in events._iter_all(store_dir):  # pylint: disable=protected-access
        gs = ev.get("graph_seq")
        if ev.get("type") == "graph.delta" and isinstance(gs, int) and since < gs <= cur:
            batches[gs] = ev
    ops: list[dict[str, Any]] = []
    last = since
    for gs in range(since + 1, cur + 1):
        ev = batches.get(gs)
        if ev is None or ev.get("reset") or not isinstance(ev.get("ops"), list):
            return {"seq": cur, "ops": [], "reset": True, "more": False}
        if ops and len(ops) + len(ev["ops"]) > limit:
            break
        ops.extend(ev["ops"])
        last = gs
    return {"seq": last, "ops": ops, "reset": False, "more": last < cur}
