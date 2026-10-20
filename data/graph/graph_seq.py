# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Graph-wide change counter and delta description for the Engram console (#209).

``graph_seq`` is a monotonic integer kept in ``<store>/graph/graph.seq`` (a sidecar, not inside
``graph.pkl``, so the control API can read it without unpickling the graph, and it is independent of
journal compaction). It is bumped under ``store_lock()`` once per *published batch* of mutations: when
the journal flushes a segment, or when ``save()`` persists ops that were never journaled. Each bump is
paired with a ``graph.delta`` event carrying the same number, so a consumer can tell a complete feed
from one with holes (events are best-effort and rotate): it asks for ``since=N`` and gets either the
contiguous batches ``N+1…current`` or ``reset: true``.

A batch is published as one ``graph.delta`` event per ``MAX_BATCH_OPS`` ops (``part`` / ``parts``, all sharing
the batch's ``graph_seq``), up to ``MAX_BATCH_TOTAL`` ops. Bigger than that (a bulk index) is published as
``reset: true`` with only an ``op_count`` — a client re-fetching the graph is cheaper than megabytes of events.
The sequence number is advanced only after every part is written, so a reader never sees a number whose
parts are still being appended.

Delta ops (``del_node`` implies removal of the node's incident edges):
  add_node {id, kind}              add_edge {src, dst, rel}
  update_node {id}                 update_edge {src, dst}
  del_node {id}                    del_edge {src, dst}
Only mutations that actually change the graph are described (a no-op ``rnd`` on a node that is still
connected produces nothing).
"""
from __future__ import annotations

import os
from typing import Any

MAX_BATCH_OPS = 200       # ops per event (one "part")
MAX_BATCH_TOTAL = 5000    # ops per batch before it is published as a bare reset (= one default journal flush)
SEQ_FILE = "graph.seq"


def seq_path(store_dir: str) -> str:
    return os.path.join(store_dir, "graph", SEQ_FILE)


def read(store_dir: str) -> int:
    """Current ``graph_seq`` of a store (0 when the graph has never published a change). Read-only."""
    try:
        with open(seq_path(store_dir), encoding="ascii") as fh:
            return max(0, int(fh.read().strip() or 0))
    except (OSError, ValueError):
        return 0


STATS_FILE = "graph.stats"


def write_stats(store_dir: str, nodes: int, edges: int) -> None:
    """Node/edge counts next to ``graph.seq`` so the metrics collector never has to unpickle the graph (#212).
    Best-effort; written after a successful ``save()``."""
    try:
        from core.config.atomic import atomic_json_dump  # pylint: disable=import-outside-toplevel
        atomic_json_dump(os.path.join(store_dir, "graph", STATS_FILE), {"nodes": nodes, "edges": edges},
                         indent=None, fsync=False)
    except Exception:  # pylint: disable=broad-except
        pass


def read_stats(store_dir: str) -> dict[str, int] | None:
    import json  # pylint: disable=import-outside-toplevel
    try:
        with open(os.path.join(store_dir, "graph", STATS_FILE), encoding="utf-8") as fh:
            data = json.load(fh)
        return {"nodes": int(data["nodes"]), "edges": int(data["edges"])}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def bump(store_dir: str) -> int:
    """Increment and persist the counter; return the new value. Caller holds ``store_lock()``."""
    from core.config.atomic import atomic_write  # pylint: disable=import-outside-toplevel
    nxt = read(store_dir) + 1
    os.makedirs(os.path.dirname(seq_path(store_dir)), exist_ok=True)
    atomic_write(seq_path(store_dir), str(nxt), fsync=False)   # change counter, not a store
    return nxt


def delta_for(graph: Any, op: tuple) -> dict[str, Any] | None:
    """Describe what applying ``op`` to ``graph`` WILL change, or ``None`` if it changes nothing
    observable. Must be called before the op is applied."""
    kind = op[0]
    if kind == "n":
        if graph.has_node(op[1]):
            return {"op": "update_node", "id": op[1]} if op[3] else None
        return {"op": "add_node", "id": op[1], "kind": op[2]}
    if kind == "e":
        if graph.has_edge(op[1], op[2]):
            return {"op": "update_edge", "src": op[1], "dst": op[2]}
        return {"op": "add_edge", "src": op[1], "dst": op[2], "rel": op[3]}
    if kind == "na":
        return {"op": "update_node", "id": op[1]} if graph.has_node(op[1]) else None
    if kind == "ea":
        return {"op": "update_edge", "src": op[1], "dst": op[2]} if graph.has_edge(op[1], op[2]) else None
    if kind == "rn":
        return {"op": "del_node", "id": op[1]} if graph.has_node(op[1]) else None
    if kind == "re":
        return {"op": "del_edge", "src": op[1], "dst": op[2]} if graph.has_edge(op[1], op[2]) else None
    if kind == "rnd":
        if graph.has_node(op[1]) and graph.degree(op[1]) <= op[2]:
            return {"op": "del_node", "id": op[1]}
        return None
    return None   # "ga" (graph attribute) and anything unknown: not a node/edge change
