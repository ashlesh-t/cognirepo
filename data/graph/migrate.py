# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Move the knowledge graph between the networkx (``graph.pkl``) and SQLite (``graph.sqlite``) backends, either
direction, and switch ``storage.graph_backend`` to the one it was moved to (#115 follow-up).

One engine for the CLI (``cognirepo graph migrate``) and the control API (a detached job running that command), so
the console never has its own copy logic. The order is what keeps it safe:

1. take the index writer lease (``JournalBusy`` -> ``busy``: an index run owns the graph);
2. set the target aside if it already exists (``replace`` required) as ``<name>.replaced-<ts>`` — the pickle's
   journal goes with it, otherwise it would replay over the new file;
3. copy (networkx -> sqlite is the #239 importer, one transaction; sqlite -> networkx streams into a fresh pickle);
4. **verify**: node and edge counts, the graph attributes, and a sample of node/edge attributes read back from the
   target; any difference undoes the copy and restores what was set aside, and the setting is NOT changed;
5. only then flip the setting.

The source is never modified. Callers that run watchers must stop them first (the CLI does); agents holding the
old backend follow the setting on their next call (``backend.is_current``).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from typing import Any, Callable

from data.graph import backend as gb
from data.graph.journal import JournalBusy, WriterLease
from data.graph.knowledge_graph import KnowledgeGraph, _graph_file, _journal_file

Progress = Callable[[dict[str, Any]], None]
SAMPLE = 200
BATCH = 10_000


class MigrationError(Exception):
    """A refused or failed migration; ``code`` is stable and machine-readable, nothing was switched."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


class _Exporter(KnowledgeGraph):  # pylint: disable=too-few-public-methods
    """A networkx-backed graph regardless of configuration (``KnowledgeGraph()`` would pick the backend)."""


def _store() -> str:
    from core.config.paths import get_cognirepo_dir  # pylint: disable=import-outside-toplevel
    return str(get_cognirepo_dir())


def _sqlite_path() -> str:
    from core.config.paths import get_path  # pylint: disable=import-outside-toplevel
    return get_path("graph/graph.sqlite")


def _other(to: str) -> str:
    return gb.NETWORKX if to == gb.SQLITE else gb.SQLITE


def _sqlite_counts(path: str) -> tuple[int, int] | None:
    """(nodes, edges) of a graph.sqlite, opened read-only; None if it is not a readable graph database."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None
    try:
        return (conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0])
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _pickle_counts(store: str, load: bool) -> tuple[int, int] | None:
    counts = gb.graph_counts(store)
    if counts is not None or not load:
        return counts
    reader = _Exporter()
    if getattr(reader, "_locked", False):
        return None
    return reader.node_count(), reader.edge_count()


def plan(to: str, *, count: bool = True) -> dict[str, Any]:
    """What ``migrate(to)`` would do, without doing anything. ``blockers`` are codes ``migrate`` would raise."""
    if to not in gb.BACKENDS:
        raise MigrationError("bad_target", f"unknown backend {to!r}; expected one of {gb.BACKENDS}")
    store, frm = _store(), _other(to)
    files = gb.graph_files(store)
    blockers: list[str] = []
    if to == gb.SQLITE and gb.encryption_on(store):
        blockers.append("encryption_on")
    if not files[frm]["exists"]:
        blockers.append("no_source")
    counts_src = None
    if files[frm]["exists"] and count:
        counts_src = _sqlite_counts(_sqlite_path()) if frm == gb.SQLITE else _pickle_counts(store, load=True)
    target_nodes = None
    if files[to]["exists"] and to == gb.SQLITE:
        tc = _sqlite_counts(_sqlite_path())
        target_nodes = None if tc is None else tc[0]
    target_has_data = files[to]["exists"] and target_nodes != 0
    aside = []
    if target_has_data:
        aside = ["graph.sqlite"] if to == gb.SQLITE else ["graph.pkl"] + (
            ["graph.journal"] if os.path.exists(_journal_file()) else [])
    nodes = counts_src[0] if counts_src else None
    return {
        "from": frm, "to": to, "store": store, "files": files,
        "nodes": nodes, "edges": counts_src[1] if counts_src else None,
        # measured peak (105k nodes / 1.28M edges: ~1.0 GB both ways) is ~2.3x the resident graph: the copy holds
        # the whole graph once and the verification step loads the result again
        "ram_mb": None if nodes is None else round(nodes * gb.KB_PER_NODE * 2.3 / 1024),
        "needs_replace": target_has_data, "moves_aside": aside, "blockers": blockers,
        "up_to_date": not gb.needs_migration(store, to) and files[to]["exists"],
    }


def _stamp() -> str:
    return time.strftime("%Y%m%d%H%M%S")


def _move_aside(paths: list[str], stamp: str) -> list[tuple[str, str]]:
    moved = []
    for src in paths:
        if os.path.exists(src):
            dst = f"{src}.replaced-{stamp}"
            os.replace(src, dst)
            moved.append((src, dst))
    return moved


def _target_files(to: str) -> list[str]:
    if to == gb.SQLITE:
        db = _sqlite_path()
        return [db, db + "-wal", db + "-shm"]
    return [_graph_file(), _journal_file()]


def _norm(value: Any) -> Any:
    from data.graph.sqlite_graph import dumps  # pylint: disable=import-outside-toplevel
    return json.loads(dumps(value if isinstance(value, dict) else {"v": value}))


def _verify(to: str, src_nodes: int, src_edges: int, src_attrs: dict, samples: list[tuple]) -> None:
    """Read the target back and compare it with what was copied; raises ``verify_failed``."""
    target: Any = _open_sqlite() if to == gb.SQLITE else _Exporter()
    try:
        if (target.node_count(), target.edge_count()) != (src_nodes, src_edges):
            raise MigrationError("verify_failed", f"target has {target.node_count()} nodes / {target.edge_count()} "
                                 f"edges, expected {src_nodes} / {src_edges}")
        got_attrs = target.graph_attrs() if hasattr(target, "graph_attrs") else dict(target.G.graph)
        for key, value in src_attrs.items():
            if key != "journal_seq" and _norm(got_attrs.get(key)) != _norm(value):
                raise MigrationError("verify_failed", f"graph attribute {key!r} differs")
        for kind, a, b, attrs in samples:
            have = target.node_attrs(a) if kind == "n" else target.edge_data(a, b)
            if have is None or _norm(have) != _norm(attrs):
                raise MigrationError("verify_failed", f"{'node' if kind == 'n' else 'edge'} "
                                     f"{a if kind == 'n' else f'{a} -> {b}'} differs after the copy")
    finally:
        if to == gb.SQLITE:
            target.close()


def _open_sqlite():
    from data.graph.sqlite_graph import SqliteGraph  # pylint: disable=import-outside-toplevel
    return SqliteGraph()


def _sample(nodes: Any, total_nodes: int, edges: Any, total_edges: int) -> list[tuple]:
    """Up to SAMPLE evenly spaced nodes and edges, taken in one pass (never the whole graph in a list)."""
    out: list[tuple] = []
    for kind, rows, total in (("n", nodes, total_nodes), ("e", edges, total_edges)):
        step, kept = max(1, total // SAMPLE), 0
        for i, row in enumerate(rows):
            if i % step == 0 and kept < SAMPLE:
                out.append(("n", row[0], None, row[1]) if kind == "n" else ("e", row[0], row[1], row[2]))
                kept += 1
    return out


def migrate(to: str, *, replace: bool = False, progress: Progress | None = None) -> dict[str, Any]:  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    """Copy the graph to backend *to*, verify it, and switch ``storage.graph_backend``. Returns a summary dict."""
    from core.config.store_settings import set_value  # pylint: disable=import-outside-toplevel

    def emit(phase: str, done: int = 0, total: int = 0) -> None:
        if progress:
            progress({"phase": phase, "done": done, "total": total})

    info = plan(to, count=False)
    if "encryption_on" in info["blockers"]:
        raise MigrationError("encryption_on", "storage.encrypt is on and the SQLite graph file is not encrypted "
                             "yet (#186); the encrypted pickle backend must stay in use")
    if "no_source" in info["blockers"]:
        raise MigrationError("no_source", f"there is no {info['from']} graph to migrate from; "
                             "run `cognirepo index-repo .` first")
    frm, started, store = info["from"], time.monotonic(), info["store"]
    emit("prepare")
    lease = WriterLease(_journal_file())
    try:
        lease.acquire(0.0)
    except JournalBusy as exc:
        raise MigrationError("busy", "an index run (or another migration) holds the graph writer lease; "
                             "try again when it finishes") from exc
    moved: list[tuple[str, str]] = []
    copy_started = False
    try:
        if to == gb.SQLITE and os.path.exists(_sqlite_path()):
            tc = _sqlite_counts(_sqlite_path())
            if tc is not None and tc[0] == 0:                # an empty shell left by an earlier open: just replace it
                for p in _target_files(to):
                    if os.path.exists(p):
                        os.remove(p)
        if any(os.path.exists(p) for p in _target_files(to)):      # incl. a leftover journal without a pickle
            if not replace:
                raise MigrationError("target_exists", f"a {to} graph already exists; pass replace to set it aside "
                                     "(it is kept as .replaced-<timestamp>)")
            moved = _move_aside(_target_files(to), _stamp())
        copy_started = True
        emit("copy")
        if to == gb.SQLITE:
            src = _Exporter()
            if getattr(src, "_locked", False):
                raise MigrationError("source_unreadable", "graph.pkl is encrypted or unreadable here")
            total_n, total_e = src.node_count(), src.edge_count()
            src_attrs = dict(src.G.graph)
            samples = _sample(((n, dict(d)) for n, d in src.G.nodes(data=True)), total_n,
                              ((u, v, dict(d)) for u, v, d in src.G.edges(data=True)), total_e)
            del src                                          # one copy of the graph in memory at a time
            emit("import", 0, total_n + total_e)
            target = _open_sqlite()                          # imports graph.pkl (+ journal) in one transaction
            try:
                target.save()
            finally:
                target.close()
        else:
            db = _open_sqlite()
            try:
                total_n, total_e = db.node_count(), db.edge_count()
                src_attrs = db.graph_attrs()
                exporter = _Exporter()
                done = 0
                nodes_sample: list[tuple] = []
                edges_sample: list[tuple] = []
                n_step, e_step = max(1, total_n // SAMPLE), max(1, total_e // SAMPLE)
                for i, (nid, attrs) in enumerate(db.iter_nodes(BATCH)):
                    nid = sys.intern(nid)       # ids are shared between nodes and edge endpoints, as in a built graph:
                    exporter.G.add_node(nid, **attrs)      # distinct copies would bloat the pickle and RSS ~2x
                    if i % n_step == 0 and len(nodes_sample) < SAMPLE:
                        nodes_sample.append(("n", nid, None, attrs))
                    done += 1
                    if done % BATCH == 0:
                        emit("export", done, total_n + total_e)
                for i, (u, v, attrs) in enumerate(db.iter_edges(BATCH)):
                    if isinstance(attrs.get("rel"), str):
                        attrs["rel"] = sys.intern(attrs["rel"])
                    exporter.G.add_edge(sys.intern(u), sys.intern(v), **attrs)
                    if i % e_step == 0 and len(edges_sample) < SAMPLE:
                        edges_sample.append(("e", u, v, attrs))
                    done += 1
                    if done % BATCH == 0:
                        emit("export", done, total_n + total_e)
                exporter.G.graph.update(src_attrs)
                samples = nodes_sample + edges_sample
                emit("write", done, total_n + total_e)
                exporter.save()
                del exporter
            finally:
                db.close()
        emit("verify", 0, len(samples))
        _verify(to, total_n, total_e, src_attrs, samples)
        emit("switch")
        changed = set_value(store, "storage", "graph_backend", to)
    except BaseException:
        if copy_started:                                      # undo: drop the partial target ...
            for p in _target_files(to):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
        for orig, aside in moved:                             # ... and put back whatever was set aside
            if os.path.exists(aside):
                os.replace(aside, orig)
        raise
    finally:
        lease.release()
    emit("done", total_n + total_e, total_n + total_e)
    return {"from": frm, "to": to, "nodes": total_n, "edges": total_e, "changed_setting": changed,
            "kept": [m[1] for m in moved], "seconds": round(time.monotonic() - started, 1),
            "env_override": gb.env_override() or None, "verified": len(samples)}
