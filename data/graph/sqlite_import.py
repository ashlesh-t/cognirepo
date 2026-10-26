# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
One-way import of an existing ``graph.pkl`` (+ its journal) into the SQLite graph (#115, ADR 002 §6).

Runs when a repo opens the SQLite backend for the first time and its database is still empty. The whole
import is ONE write transaction: other processes keep seeing "no graph yet" until it commits, and a kill
mid-way leaves nothing behind (SQLite rolls it back), so there is no half-imported state to detect or
repair. A ``meta.import_state`` row written in the same transaction makes it idempotent — an opened,
populated or already-imported database is never touched again. ``graph.pkl`` and ``graph.journal`` are
only read; they stay as the fallback for switching ``storage.graph_backend`` back to ``networkx``.

Cost: the pickle is loaded whole once (what every process pays today), then streamed in batches.
"""
from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING, Any, Iterator

from data.graph.knowledge_graph import KnowledgeGraph, _graph_file

if TYPE_CHECKING:  # pragma: no cover
    from data.graph.sqlite_graph import SqliteGraph

BATCH = 10_000


class _PickleReader(KnowledgeGraph):  # pylint: disable=too-few-public-methods
    """A networkx-backed graph regardless of configuration (``KnowledgeGraph()`` would pick the backend)."""


def _chunks(rows: Iterator[tuple], size: int = BATCH) -> Iterator[list[tuple]]:
    chunk: list[tuple] = []
    for row in rows:
        chunk.append(row)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def import_if_needed(graph: "SqliteGraph") -> dict[str, Any] | None:
    """Import ``graph.pkl`` into *graph*'s empty database. Returns counts, or None when nothing was done."""
    if not os.path.exists(_graph_file()):
        return None
    if graph.node_count() or graph._one("SELECT 1 FROM meta WHERE key='import_state'"):  # pylint: disable=protected-access
        return None
    reader = _PickleReader()
    if getattr(reader, "_locked", False):
        return None            # unreadable (e.g. encrypted): leave it for a run that can read it
    if reader.node_count() == 0:
        # An empty pickle has nothing to import; say so, or every start would unpickle it again to find out.
        # pylint: disable=protected-access
        graph._db().execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('import_state', ?)",
                            (json.dumps({"source": "graph.pkl", "nodes": 0, "edges": 0, "seconds": 0}),))
        return None
    return _import(graph, reader)


def _import(graph: "SqliteGraph", reader: KnowledgeGraph) -> dict[str, Any] | None:
    from data.graph.sqlite_graph import dumps  # pylint: disable=import-outside-toplevel
    started = time.monotonic()
    nodes = edges = 0
    # pylint: disable=protected-access
    with graph._rlock:
        conn = graph._db()
        conn.execute("BEGIN IMMEDIATE")
        try:
            if (conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
                    or conn.execute("SELECT 1 FROM meta WHERE key='import_state'").fetchone()):
                conn.execute("ROLLBACK")      # another process imported while we were reading the pickle
                return None

            def node_rows() -> Iterator[tuple]:
                for nid, data in reader.G.nodes(data=True):
                    attrs = {k: v for k, v in data.items() if k != "type"}
                    file = attrs.get("file")
                    yield nid, data.get("type"), file if isinstance(file, str) else None, dumps(attrs)

            def edge_rows() -> Iterator[tuple]:
                for src, dst, data in reader.G.edges(data=True):
                    attrs = {k: v for k, v in data.items() if k not in ("rel", "weight")}
                    yield src, dst, data.get("rel"), data.get("weight"), dumps(attrs)

            for chunk in _chunks(node_rows()):
                conn.executemany("INSERT INTO nodes(id, type, file, attrs) VALUES (?,?,?,?)", chunk)
                nodes += len(chunk)
            for chunk in _chunks(edge_rows()):
                conn.executemany("INSERT INTO edges(src, dst, rel, weight, attrs) VALUES (?,?,?,?,?)", chunk)
                edges += len(chunk)
            for key, value in reader.G.graph.items():
                if key != "journal_seq":      # the pickle backend's journal bookkeeping; meaningless here
                    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)",
                                 (f"ga:{key}", json.dumps(value, default=str)))
            summary = {"source": "graph.pkl", "nodes": nodes, "edges": edges,
                       "seconds": round(time.monotonic() - started, 3)}
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('import_state', ?)",
                         (json.dumps(summary),))
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except Exception:  # pylint: disable=broad-except
                pass
            raise
    return summary
