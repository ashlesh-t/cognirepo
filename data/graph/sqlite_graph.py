# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
SQLite (WAL) backend for the knowledge graph (#115, ADR 002). Opt-in: ``storage.graph_backend: sqlite``.

Same public surface as ``KnowledgeGraph`` (it is a subclass, so ``isinstance`` checks and the ~50
``KnowledgeGraph()`` call sites keep working), different storage:

* **Nothing is loaded whole.** Nodes and edges live in ``.cognirepo/graph/graph.sqlite``; every read is
  an indexed query (``COUNT(*)``, adjacency by ``src`` / ``dst``, bounded BFS for paths and subgraphs)
  with a small LRU of hot adjacency lists. Resident memory stops scaling with graph size, and a second
  process opening the graph costs a connection, not a copy.
* **No journal, no rebase.** A mutation is applied to the database at once, inside a write transaction
  that ``save()`` (or the end of an index run, or a flush) commits. There is no stale in-memory copy to
  overwrite newer state with, so ``_pending`` / ``_rebase`` / ``graph.journal`` do not exist here. Committed
  batches are durable, so a killed ``index-repo`` resumes from the committed rows; the uncommitted tail of
  the open transaction is discarded by SQLite on the next open.
* **Same writer lease.** ``index-repo`` still takes ``journal.WriterLease`` (it also guards the AST index
  and the vector store), so two indexers still refuse each other with ``JournalBusy``.
* **Same change feed (#209).** Deltas are recorded per op and published as one ``graph.delta`` batch per
  commit; ``graph.stats`` is written by ``save()``.

Attribute values are stored as JSON: tuples come back as lists, sets as sorted lists, other
non-JSON objects as strings. The importer and live writes go through the same normalisation, so the two
paths agree. Path and hop searches are bounded (``MAX_DEPTH`` / ``MAX_VISITED``) instead of walking the
whole graph; beyond the bound they answer "no path", which retrieval treats as "far away".
"""
from __future__ import annotations

import atexit
import json
import os
import sqlite3
import sys
import threading
import time
import warnings
import weakref
from collections import OrderedDict
from typing import Any, Iterable

from core.config.paths import get_path
from data.graph import graph_seq as _graph_seq
from data.graph import journal as _journal
from data.graph.knowledge_graph import (
    PYTHON_BUILTINS, KnowledgeGraph, NodeType, _journal_file,
)

SCHEMA_VERSION = 1
#: adjacency lists kept in memory per direction (ADR 002 §4)
ADJACENCY_CACHE = 10_000
#: bounds for path / hop searches; past them the answer is "not connected"
MAX_DEPTH = 16
MAX_VISITED = 20_000
#: a write transaction left open (no save/flush) is committed after this long without activity …
IDLE_COMMIT_SECS = 5.0
#: … and, outside an index run, after this long even under continuous activity, so it never starves other writers
TX_MAX_SECS = 60.0
BUSY_TIMEOUT_SECS = 30.0
#: ``BEGIN IMMEDIATE`` is retried on "database is locked" for this long in total (each attempt already waits
#: BUSY_TIMEOUT_SECS), which is longer than the longest transaction another process may legitimately hold
#: (TX_MAX_SECS), so a busy writer is waited for rather than failed
LOCK_WAIT_SECS = 150.0
#: an index run's open transaction is committed at least this often, so other writers (the watcher, MCP tools)
#: wait seconds for the write lock, not for the length of the run; the configured flush interval is a ceiling
MAX_FLUSH_SECS = 5.0
#: how often a reader re-checks whether another process committed (invalidates the adjacency cache)
_FRESHNESS_SECS = 1.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY, type TEXT, file TEXT, attrs TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS edges (
    src TEXT NOT NULL, dst TEXT NOT NULL, rel TEXT, weight REAL, attrs TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (src, dst));
CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst);
CREATE INDEX IF NOT EXISTS nodes_file ON nodes(file);
CREATE INDEX IF NOT EXISTS nodes_type ON nodes(type);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

_OPEN: "weakref.WeakSet[SqliteGraph]" = weakref.WeakSet()


def sqlite_file() -> str:
    """Path of the graph database for the repo the current context points at."""
    return get_path("graph/graph.sqlite")


def _json_default(value: Any) -> Any:
    if isinstance(value, (set, frozenset)):
        try:
            return sorted(value)
        except TypeError:
            return list(value)
    return str(value)


def dumps(attrs: dict) -> str:
    """Attribute dict -> JSON text (the one normalisation shared by live writes and the importer)."""
    if not attrs:
        return "{}"
    return json.dumps(attrs, default=_json_default, separators=(",", ":"), ensure_ascii=False)


# Bandit B608 ("SQL built from strings") is suppressed on the f-string queries below: the only things
# interpolated are fixed fragments of this module (_NO_EDGES, the src/dst column names) and strings of
# "?" placeholders; every value, including every node id, is bound as a parameter.
_DEGREE_SQL = ("SELECT (SELECT COUNT(*) FROM edges WHERE src=?1) + (SELECT COUNT(*) FROM edges WHERE dst=?1) "
               "WHERE EXISTS (SELECT 1 FROM nodes WHERE id=?1)")
#: ids per ``IN (...)`` query; well under SQLite's variable limit
_CHUNK = 500


class _Seen:  # pylint: disable=too-few-public-methods
    """Just enough of a graph for ``graph_seq.delta_for``, answered from the one row already fetched for the op."""

    def __init__(self, pre: Any) -> None:
        self._pre = pre

    def has_node(self, _node: str) -> bool:
        return self._pre is not None

    def has_edge(self, _src: str, _dst: str) -> bool:
        return self._pre is not None

    def degree(self, _node: str) -> int:
        return self._pre if isinstance(self._pre, int) else 0


def _is_corruption(exc: sqlite3.DatabaseError) -> bool:
    """Only a database SQLite itself calls broken is moved aside; an I/O, permission or lock error is not."""
    text = str(exc).lower()
    return "malformed" in text or "not a database" in text


def _file_of(attrs: dict) -> str | None:
    value = attrs.get("file")
    return value if isinstance(value, str) else None


@atexit.register
def _commit_open_graphs() -> None:  # pragma: no cover - interpreter shutdown
    for graph in list(_OPEN):
        try:
            graph.close()
        except Exception:  # pylint: disable=broad-except
            pass


class SqliteUndirectedView:  # pylint: disable=too-few-public-methods
    """Hop distances ignoring direction, computed on demand (a networkx copy would defeat the point)."""

    def __init__(self, graph: "SqliteGraph") -> None:
        self._graph = graph

    def hops(self, src: str, dst: str) -> int | None:
        path = self._graph.path_between(src, dst, undirected=True)
        return None if path is None else len(path) - 1


class SqliteGraph(KnowledgeGraph):  # pylint: disable=too-many-public-methods
    """``KnowledgeGraph`` over a SQLite database. See the module docstring."""

    def __init__(self) -> None:  # pylint: disable=super-init-not-called
        # No super().__init__(): there is no pickle to load and no in-memory graph to build.
        self._path = sqlite_file()
        self._disk_path = self._path
        self._rlock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._in_tx = False
        self._tx_started = 0.0
        self._last_activity = 0.0
        self._idle_timer: threading.Timer | None = None
        self._adj: dict[bool, "OrderedDict[str, list[str]]"] = {True: OrderedDict(), False: OrderedDict()}
        self._data_version: int | None = None
        self._fresh_checked = 0.0
        self._journal_active = False
        self._lease: "_journal.WriterLease | None" = None
        self._flush_ops = 5000
        self._flush_secs = 30.0
        self._ops_since_flush = 0
        self._last_flush = time.monotonic()
        self._deltas: list = []
        self._delta_count = 0
        self._delta_overflow = False
        self._locked = False
        self._open()
        _OPEN.add(self)

    # ── no networkx here ──────────────────────────────────────────────────────

    @property
    def G(self) -> Any:  # pylint: disable=invalid-name
        raise AttributeError(
            "the SQLite graph backend has no in-memory networkx graph; use the KnowledgeGraph "
            "read facade (node_attrs, successors, predecessors, edge_data, degree, ...)")

    # ── connection ────────────────────────────────────────────────────────────

    def _open(self) -> None:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        try:
            self._connect()
        except sqlite3.DatabaseError as exc:
            if not _is_corruption(exc):
                raise       # locked, unreadable, read-only, disk error...: the file may be perfectly healthy
            self._quarantine(exc)
            self._connect()
        from data.graph.sqlite_import import import_if_needed  # pylint: disable=import-outside-toplevel
        try:
            import_if_needed(self)
        except sqlite3.OperationalError as exc:  # another process is importing: it will land, we read it then
            warnings.warn(f"SqliteGraph: pickle import skipped for now ({exc}).", stacklevel=2)
        self._data_version = self._pragma("data_version")

    def _connect(self) -> None:
        conn = sqlite3.connect(self._path, timeout=BUSY_TIMEOUT_SECS, isolation_level=None,
                               check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")   # derived data: a lost last commit costs a re-index
            conn.execute("PRAGMA cache_size=-8192")     # 8 MiB page cache per connection
            conn.execute("PRAGMA journal_size_limit=8388608")   # a checkpointed WAL shrinks back to 8 MiB
            conn.executescript(_SCHEMA)
            row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row is None:
                conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
                             (str(SCHEMA_VERSION),))
            elif int(row[0]) > SCHEMA_VERSION:
                raise RuntimeError(
                    f"{self._path} was written by a newer cognirepo (graph schema {row[0]} > "
                    f"{SCHEMA_VERSION}); upgrade, or set storage.graph_backend to networkx")
        except BaseException:
            conn.close()
            raise
        self._conn = conn

    def _quarantine(self, exc: Exception) -> None:
        """Unreadable database: move it (and its WAL files) aside and start empty — mirrors graph.pkl."""
        stamp = int(time.time())
        moved = None
        for suffix in ("", "-wal", "-shm"):
            src = self._path + suffix
            if os.path.exists(src):
                try:
                    os.replace(src, f"{self._path}.corrupt-{stamp}{suffix}")
                    moved = moved or f"{self._path}.corrupt-{stamp}"
                except OSError:
                    pass
        warnings.warn(
            f"SqliteGraph: could not open {self._path} ({exc}). "
            + (f"Quarantined it to {moved}. " if moved else "")
            + "Starting with an empty graph. Re-run `cognirepo index-repo` to rebuild.",
            stacklevel=3,
        )

    def close(self) -> None:
        """Commit what is pending and release the connection and any writer lease."""
        with self._rlock:
            if self._conn is None:
                return
            try:
                self._commit()
            finally:
                self._cancel_idle()
                if self._lease is not None:
                    self._lease.release()
                    self._lease = None
                    self._journal_active = False
                self._conn.close()
                self._conn = None

    def __del__(self) -> None:  # pragma: no cover - best effort
        try:
            self.close()
        except Exception:  # pylint: disable=broad-except
            pass

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("SqliteGraph is closed")
        return self._conn

    def _all(self, sql: str, args: Iterable = ()) -> list[tuple]:
        with self._rlock:
            return self._db().execute(sql, tuple(args)).fetchall()

    def _one(self, sql: str, args: Iterable = ()) -> tuple | None:
        with self._rlock:
            return self._db().execute(sql, tuple(args)).fetchone()

    def _pragma(self, name: str) -> int:
        row = self._one(f"PRAGMA {name}")
        return int(row[0]) if row else 0

    # ── transactions ──────────────────────────────────────────────────────────

    def _begin(self) -> None:
        if self._in_tx:
            return
        started = time.monotonic()
        while True:
            try:
                self._db().execute("BEGIN IMMEDIATE")
                break
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc) and "busy" not in str(exc):
                    raise
                if time.monotonic() - started > LOCK_WAIT_SECS:
                    raise
                time.sleep(0.05)
        self._in_tx = True
        self._tx_started = time.monotonic()
        if not self._journal_active:
            self._arm_idle()

    def _commit(self) -> None:
        """Make this instance's writes durable and visible to other processes, then publish their deltas."""
        with self._rlock:
            if self._in_tx:
                self._db().execute("COMMIT")
                self._in_tx = False
            self._cancel_idle()
            self._ops_since_flush = 0
            self._last_flush = time.monotonic()
        self._publish_deltas()

    def _arm_idle(self) -> None:
        if self._idle_timer is None:
            self._idle_timer = threading.Timer(IDLE_COMMIT_SECS, self._idle_commit)
            self._idle_timer.daemon = True
            self._idle_timer.start()

    def _cancel_idle(self) -> None:
        timer, self._idle_timer = self._idle_timer, None
        if timer is not None:
            timer.cancel()

    def _idle_commit(self) -> None:
        """Timer callback: commit a transaction nobody has saved, so it can't hold the write lock forever."""
        with self._rlock:
            self._idle_timer = None
            if self._conn is None or not self._in_tx or self._journal_active:
                return
            quiet = time.monotonic() - self._last_activity
            if quiet < IDLE_COMMIT_SECS:        # still being written to: look again when it would be idle
                self._idle_timer = threading.Timer(IDLE_COMMIT_SECS - quiet, self._idle_commit)
                self._idle_timer.daemon = True
                self._idle_timer.start()
                return
            try:
                self._commit()
            except Exception as exc:  # pylint: disable=broad-except
                warnings.warn(f"SqliteGraph: idle commit failed ({exc}).", stacklevel=2)

    # ── persistence API (same names as KnowledgeGraph) ────────────────────────

    def save(self) -> None:
        """Commit. (The pickle backend serialises the whole graph here; this one only commits.)"""
        with self._rlock:
            self._commit()
            try:
                self._db().execute("PRAGMA wal_checkpoint(PASSIVE)")   # never blocks on readers
            except sqlite3.Error:
                pass
            try:
                from core.config.paths import get_cognirepo_dir  # pylint: disable=import-outside-toplevel
                _graph_seq.write_stats(str(get_cognirepo_dir()), self.node_count(), self.edge_count())
            except Exception:  # pylint: disable=broad-except
                pass

    def _load(self) -> None:
        """Forget cached reads; the database is always current."""
        with self._rlock:
            for cache in self._adj.values():
                cache.clear()
            self._data_version = self._pragma("data_version")

    def reload_if_changed(self) -> bool:
        """True when another process committed since this was last asked (callers then drop derived caches)."""
        if self._disk_path is not None and sqlite_file() != self._disk_path:
            return False  # a _repo_ctx() has repointed get_path() at another repo
        if self._journal_active:
            return False
        with self._rlock:
            version = self._pragma("data_version")
            if version == self._data_version:
                return False
            self._data_version = version
            for cache in self._adj.values():
                cache.clear()
            return True

    def begin_journal(self, flush_ops: int = 5000, flush_secs: float = 30.0, flush_bytes: int = 0,
                      wait: float = 0.0) -> None:
        """Start a batched index run: take the writer lease (``JournalBusy`` if another process holds it)
        and commit every ``flush_ops`` ops / ``flush_secs`` seconds (at most ``MAX_FLUSH_SECS``: the open
        transaction holds the database's write lock). ``flush_bytes`` is accepted for
        signature parity; rows go straight to the database, so there is no buffer to bound by size."""
        del flush_bytes
        lease = _journal.WriterLease(_journal_file())
        lease.acquire(wait)
        with self._rlock:
            self._lease = lease
            self._flush_ops = max(1, int(flush_ops))
            self._flush_secs = min(float(flush_secs), MAX_FLUSH_SECS)
            self._ops_since_flush = 0
            self._last_flush = time.monotonic()
            self._cancel_idle()
            self._journal_active = True

    def end_journal(self) -> None:
        """Commit and release the writer lease."""
        try:
            if self._journal_active:
                self.flush_journal()
        finally:
            with self._rlock:
                self._journal_active = False
                if self._lease is not None:
                    self._lease.release()
                    self._lease = None

    def flush_journal(self) -> None:
        """Commit the batch so far (durable, visible to other processes) and publish its change feed."""
        self._commit()

    def maybe_flush(self) -> None:
        """Commit when enough ops or time accumulated. Never raises: a commit problem must not abort indexing."""
        if not self._journal_active:
            return
        with self._rlock:
            if (self._ops_since_flush < self._flush_ops
                    and time.monotonic() - self._last_flush < self._flush_secs):
                return
            try:
                self._commit()
            except Exception as exc:  # pylint: disable=broad-except
                warnings.warn(f"SqliteGraph: batch commit failed ({exc}); will retry on the next flush.",
                              stacklevel=2)

    # ── mutation (the primitive ops of KnowledgeGraph._apply, as SQL) ─────────

    def _pre(self, op: tuple) -> Any:
        """What the database holds for the thing *op* touches, read ONCE and shared by the change-feed
        description and the write: the node row, the edge row, or (conditional prune) the node's degree."""
        conn, kind = self._db(), op[0]
        if kind in ("n", "na", "rn"):
            return conn.execute("SELECT type, attrs FROM nodes WHERE id=?", (op[1],)).fetchone()
        if kind in ("e", "ea", "re"):
            return conn.execute("SELECT rel, weight, attrs FROM edges WHERE src=? AND dst=?",
                                (op[1], op[2])).fetchone()
        if kind == "rnd":
            row = conn.execute(_DEGREE_SQL, (op[1],)).fetchone()
            return None if row is None else row[0]
        return None

    def _apply(self, op: tuple) -> None:
        with self._rlock:
            self._begin()
            self._write(op, self._pre(op))

    def _do(self, op: tuple) -> None:
        with self._rlock:
            self._begin()                       # before reading: nobody can change the row between read and write
            pre = self._pre(op)
            delta = _graph_seq.delta_for(_Seen(pre), op)
            self._write(op, pre)
            if delta is not None:
                self._record_delta(delta)
            self._last_activity = time.monotonic()
            if self._journal_active:
                self._ops_since_flush += 1
                if self._ops_since_flush >= self._flush_ops:
                    self.maybe_flush()
            elif self._in_tx and self._last_activity - self._tx_started > TX_MAX_SECS:
                self._commit()

    def _write(self, op: tuple, pre: Any) -> None:  # pylint: disable=too-many-branches
        kind = op[0]
        self._invalidate(op, pre)
        conn = self._db()
        if kind == "n":
            _, nid, ntype, attrs = op
            if pre is None:
                attrs = dict(attrs)
                conn.execute("INSERT INTO nodes(id, type, file, attrs) VALUES (?,?,?,?)",
                             (nid, ntype, _file_of(attrs), dumps(attrs)))
            else:
                self._merge_node(nid, pre[1], attrs)
        elif kind == "e":
            self._write_edge(pre, *op[1:])
        elif kind == "na":
            if pre is not None:
                self._merge_node(op[1], pre[1], op[2])
        elif kind == "ea":
            if pre is not None:
                self._merge_edge(op[1], op[2], pre, op[3], None)
        elif kind == "rn":
            if pre is not None:
                self._delete_node(op[1])
        elif kind == "re":
            if pre is not None:
                conn.execute("DELETE FROM edges WHERE src=? AND dst=?", (op[1], op[2]))
        elif kind == "ga":
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)",
                         (f"ga:{op[1]}", json.dumps(op[2], default=_json_default)))
        elif kind == "rnd":
            if pre is not None and pre <= op[2]:
                self._delete_node(op[1])
        else:
            raise ValueError(f"unknown graph op {kind!r}")

    def _invalidate(self, op: tuple, pre: Any) -> None:
        """Forget only the cached adjacency lists this op changes (attribute-only ops change none)."""
        kind = op[0]
        out, inc = self._adj[True], self._adj[False]
        if kind in ("e", "re"):
            if kind == "re" and pre is None:
                return
            out.pop(op[1], None)
            inc.pop(op[2], None)
        elif kind in ("rn", "rnd") and pre is not None:
            nid = op[1]
            for pred in self._adjacent(nid, False):
                out.pop(pred, None)
            for succ in self._adjacent(nid, True):
                inc.pop(succ, None)
            out.pop(nid, None)
            inc.pop(nid, None)

    def _merge_node(self, nid: str, old_attrs: str, attrs: dict) -> None:
        merged = json.loads(old_attrs)
        merged.update(attrs)
        ntype = merged.pop("type", None)    # networkx stores the type as an ordinary attribute
        if ntype is None:
            self._db().execute("UPDATE nodes SET file=?, attrs=? WHERE id=?",
                               (_file_of(merged), dumps(merged), nid))
        else:
            self._db().execute("UPDATE nodes SET type=?, file=?, attrs=? WHERE id=?",
                               (ntype, _file_of(merged), dumps(merged), nid))

    def _write_edge(self, pre: Any, src: str, dst: str, rel: str | None, weight: float | None,
                    attrs: dict) -> None:
        if pre is not None:
            self._merge_edge(src, dst, pre, attrs, weight)
            return
        a = dict(attrs)                     # networkx add_edge creates missing endpoints, with no attributes
        a_rel, a_weight = a.pop("rel", None), a.pop("weight", None)
        conn = self._db()
        conn.execute("INSERT OR IGNORE INTO nodes(id, type, file, attrs) VALUES (?,NULL,NULL,'{}'),(?,NULL,NULL,'{}')",
                     (src, dst))
        conn.execute("INSERT INTO edges(src, dst, rel, weight, attrs) VALUES (?,?,?,?,?)",
                     (src, dst, rel if rel is not None else a_rel,
                      weight if weight is not None else a_weight, dumps(a)))

    def _merge_edge(self, src: str, dst: str, pre: tuple, attrs: dict, weight: float | None) -> None:
        rel, old_weight, old = pre
        merged = json.loads(old)
        merged.update(attrs)
        rel = merged.pop("rel", rel)
        new_weight = merged.pop("weight", old_weight if weight is None else weight)
        self._db().execute("UPDATE edges SET rel=?, weight=?, attrs=? WHERE src=? AND dst=?",
                           (rel, new_weight, dumps(merged), src, dst))

    def _delete_node(self, nid: str) -> None:
        conn = self._db()
        conn.execute("DELETE FROM edges WHERE src=? OR dst=?", (nid, nid))
        conn.execute("DELETE FROM nodes WHERE id=?", (nid,))

    # ── reads ─────────────────────────────────────────────────────────────────

    def _fresh(self) -> None:
        """Drop cached adjacency if another process committed (checked at most once a second)."""
        now = time.monotonic()
        if now - self._fresh_checked < _FRESHNESS_SECS:
            return
        self._fresh_checked = now
        version = self._pragma("data_version")
        if version != self._data_version:
            self._data_version = version
            for cache in self._adj.values():
                cache.clear()

    def _adjacent(self, node_id: str, outgoing: bool) -> list[str]:
        with self._rlock:
            self._fresh()
            cache = self._adj[outgoing]
            hit = cache.get(node_id)
            if hit is not None:
                cache.move_to_end(node_id)
                return list(hit)
            sql = ("SELECT dst FROM edges WHERE src=? ORDER BY rowid" if outgoing
                   else "SELECT src FROM edges WHERE dst=? ORDER BY rowid")
            found = [r[0] for r in self._all(sql, (node_id,))]
            cache[node_id] = found
            if len(cache) > ADJACENCY_CACHE:
                cache.popitem(last=False)
            return list(found)

    def node_exists(self, node_id: str) -> bool:
        return self._one("SELECT 1 FROM nodes WHERE id=?", (node_id,)) is not None

    has_node = node_exists

    def has_edge(self, src: str, dst: str) -> bool:
        return self._one("SELECT 1 FROM edges WHERE src=? AND dst=?", (src, dst)) is not None

    def node_count(self) -> int:
        return self._one("SELECT COUNT(*) FROM nodes")[0]

    def edge_count(self) -> int:
        return self._one("SELECT COUNT(*) FROM edges")[0]

    def stats(self) -> dict:
        return {"nodes": self.node_count(), "edges": self.edge_count()}

    def node_ids(self) -> list[str]:
        return [r[0] for r in self._all("SELECT id FROM nodes ORDER BY rowid")]

    @staticmethod
    def _node_dict(ntype: str | None, attrs: str) -> dict:
        data: dict = {} if ntype is None else {"type": ntype}
        if attrs != "{}":
            data.update(json.loads(attrs))
        return data

    def nodes_with_data(self) -> list[tuple[str, dict]]:
        return [(r[0], self._node_dict(r[1], r[2]))
                for r in self._all("SELECT id, type, attrs FROM nodes ORDER BY rowid")]

    def node_attrs(self, node_id: str) -> dict:
        row = self._one("SELECT type, attrs FROM nodes WHERE id=?", (node_id,))
        return {} if row is None else self._node_dict(*row)

    def successors(self, node_id: str) -> list[str]:
        return self._adjacent(node_id, True)

    def predecessors(self, node_id: str) -> list[str]:
        return self._adjacent(node_id, False)

    @staticmethod
    def _edge_dict(rel: str | None, weight: float | None, attrs: str) -> dict:
        data = json.loads(attrs) if attrs != "{}" else {}
        if rel is not None:
            data["rel"] = rel
        if weight is not None:
            data["weight"] = weight
        return data

    def edge_data(self, src: str, dst: str) -> dict | None:
        row = self._one("SELECT rel, weight, attrs FROM edges WHERE src=? AND dst=?", (src, dst))
        return None if row is None else self._edge_dict(*row)

    def edges_with_data(self) -> list[tuple[str, str, dict]]:
        return [(r[0], r[1], self._edge_dict(r[2], r[3], r[4]))
                for r in self._all(     # networkx order: grouped by source node, each source's edges in insertion order
                    "SELECT e.src, e.dst, e.rel, e.weight, e.attrs FROM edges e JOIN nodes n ON n.id = e.src "
                    "ORDER BY n.rowid, e.rowid")]

    def degree(self, node_id: str) -> int:
        row = self._one(_DEGREE_SQL, (node_id,))
        return 0 if row is None else row[0]

    def in_degrees(self) -> list[tuple[str, int]]:
        return [(r[0], r[1]) for r in self._all(
            "SELECT n.id, (SELECT COUNT(*) FROM edges e WHERE e.dst = n.id) FROM nodes n ORDER BY n.rowid")]

    def iter_nodes(self, batch: int = 10_000):
        """Yield ``(id, attrs)`` in insertion order without holding the whole graph (keyset pagination)."""
        last = 0
        while True:
            rows = self._all("SELECT rowid, id, type, attrs FROM nodes WHERE rowid > ? ORDER BY rowid LIMIT ?",
                             (last, batch))
            if not rows:
                return
            for rowid, nid, ntype, attrs in rows:
                last = rowid
                yield nid, self._node_dict(ntype, attrs)

    def iter_edges(self, batch: int = 10_000):
        """Yield ``(src, dst, attrs)`` in insertion order without holding the whole graph."""
        last = 0
        while True:
            rows = self._all("SELECT rowid, src, dst, rel, weight, attrs FROM edges WHERE rowid > ? "
                             "ORDER BY rowid LIMIT ?", (last, batch))
            if not rows:
                return
            for rowid, src, dst, rel, weight, attrs in rows:
                last = rowid
                yield src, dst, self._edge_dict(rel, weight, attrs)

    def graph_attrs(self) -> dict[str, Any]:
        """All graph-level attributes (e.g. ``complete``)."""
        return {k[3:]: json.loads(v) for k, v in self._all("SELECT key, value FROM meta WHERE key LIKE 'ga:%'")}

    def graph_attr(self, key: str, default: Any = None) -> Any:
        row = self._one("SELECT value FROM meta WHERE key=?", (f"ga:{key}",))
        return default if row is None else json.loads(row[0])

    def count_nodes_of_type(self, node_type: str) -> int:
        return self._one("SELECT COUNT(*) FROM nodes WHERE type=?", (node_type,))[0]

    _NO_EDGES = ("NOT EXISTS (SELECT 1 FROM edges e WHERE e.src = n.id OR e.dst = n.id)")

    def isolated_node_ids(self) -> list[str]:
        return [r[0] for r in self._all(f"SELECT n.id FROM nodes n WHERE {self._NO_EDGES} ORDER BY n.rowid")]  # nosec B608

    def top_degree_ids(self, limit: int) -> list[str]:
        return [r[0] for r in self._all(
            "SELECT n.id FROM nodes n ORDER BY (SELECT COUNT(*) FROM edges WHERE src = n.id) "
            "+ (SELECT COUNT(*) FROM edges WHERE dst = n.id) DESC, n.rowid LIMIT ?", (max(0, limit),))]

    def nodes_for_file(self, file_path: str) -> list[str]:
        return [r[0] for r in self._all("SELECT id FROM nodes WHERE file=? ORDER BY rowid", (file_path,))]

    def orphan_stubs(self) -> list[str]:
        return [r[0] for r in self._all(
            f"SELECT n.id FROM nodes n WHERE substr(n.id, 1, 8) = 'symbol::' AND n.type = ? AND {self._NO_EDGES} "  # nosec B608
            "ORDER BY n.rowid", (NodeType.CONCEPT,))]

    # ── batched reads (one query per _CHUNK ids instead of one per id) ─────────

    def _adjacent_many(self, nodes: list[str], outgoing: bool) -> dict[str, list[str]]:
        """Adjacency of several nodes at once (insertion order per node); fills the LRU."""
        with self._rlock:
            self._fresh()
            cache = self._adj[outgoing]
            out: dict[str, list[str]] = {}
            missing: list[str] = []
            for node in dict.fromkeys(nodes):
                hit = cache.get(node)
                if hit is None:
                    missing.append(node)
                else:
                    cache.move_to_end(node)
                    out[node] = hit
            key, val = ("src", "dst") if outgoing else ("dst", "src")
            for i in range(0, len(missing), _CHUNK):
                chunk = missing[i:i + _CHUNK]
                found: dict[str, list[str]] = {n: [] for n in chunk}
                for k, v in self._all(
                        f"SELECT {key}, {val} FROM edges WHERE {key} IN ({','.join('?' * len(chunk))}) "  # nosec B608
                        "ORDER BY rowid", chunk):
                    found[k].append(v)
                for node, lst in found.items():
                    cache[node] = lst
                    out[node] = lst
            while len(cache) > ADJACENCY_CACHE:
                cache.popitem(last=False)
            return out

    def _degrees_many(self, ids: Iterable[str]) -> dict[str, int]:
        ids = list(dict.fromkeys(ids))
        out: dict[str, int] = {}
        for i in range(0, len(ids), _CHUNK):
            chunk = ids[i:i + _CHUNK]
            for node, deg in self._all(
                    "SELECT n.id, (SELECT COUNT(*) FROM edges WHERE src = n.id) "  # nosec B608
                    "+ (SELECT COUNT(*) FROM edges WHERE dst = n.id) FROM nodes n "
                    f"WHERE n.id IN ({','.join('?' * len(chunk))})", chunk):
                out[node] = deg
        return out

    def _node_attrs_many(self, ids: Iterable[str]) -> dict[str, dict]:
        ids = list(dict.fromkeys(ids))
        out: dict[str, dict] = {}
        for i in range(0, len(ids), _CHUNK):
            chunk = ids[i:i + _CHUNK]
            for node, ntype, attrs in self._all(
                    f"SELECT id, type, attrs FROM nodes WHERE id IN ({','.join('?' * len(chunk))})", chunk):  # nosec B608
                out[node] = self._node_dict(ntype, attrs)
        return out

    # ── searches (bounded; the pickle backend walks the whole graph) ──────────

    def _search(self, src: str, dst: str, undirected: bool) -> list[str] | None:
        """Shortest path by bidirectional BFS (one whole level of the smaller side at a time), at most
        MAX_DEPTH hops and MAX_VISITED nodes. Among equally short paths, which one is returned is arbitrary."""
        if not self.node_exists(src) or not self.node_exists(dst):
            return None
        if src == dst:
            return [src]
        dist = ({src: 0}, {dst: 0})                 # forward from src, backward from dst
        parent: tuple[dict, dict] = ({src: None}, {dst: None})
        front = ([src], [dst])
        while front[0] and front[1] and dist[0][front[0][0]] + dist[1][front[1][0]] < MAX_DEPTH:
            if len(dist[0]) + len(dist[1]) >= MAX_VISITED:
                return None
            side = 0 if len(front[0]) <= len(front[1]) else 1       # expand the cheaper frontier
            outgoing = side == 0
            adj = self._adjacent_many(front[side], outgoing)
            adj_other = self._adjacent_many(front[side], not outgoing) if undirected else {}
            best_total, best_node = MAX_DEPTH + 1, None     # a meeting longer than MAX_DEPTH counts as none
            nxt: list[str] = []
            for node in front[side]:
                for nb in (*adj[node], *adj_other.get(node, ())):
                    if nb in dist[side]:
                        continue
                    dist[side][nb] = dist[side][node] + 1
                    parent[side][nb] = node
                    nxt.append(nb)
                    if nb in dist[1 - side]:
                        total = dist[side][nb] + dist[1 - side][nb]
                        if total < best_total:
                            best_total, best_node = total, nb
            if best_node is not None:
                meet = best_node
                left, node = [], meet
                while node is not None:
                    left.append(node)
                    node = parent[0][node]
                path = left[::-1]
                node = parent[1][meet]
                while node is not None:
                    path.append(node)
                    node = parent[1][node]
                return path
            front = (nxt, front[1]) if side == 0 else (front[0], nxt)
        return None

    def undirected_snapshot(self) -> SqliteUndirectedView:  # type: ignore[override]
        return SqliteUndirectedView(self)

    def path_between(self, src: str, dst: str, undirected: bool = False) -> list[str] | None:
        return self._search(src, dst, undirected)

    def shortest_path(self, src: str, dst: str) -> list[str] | None:
        return self._search(src, dst, False)

    def hop_distance(self, src: str, dst: str) -> int:
        path = self._search(src, dst, False)
        return sys.maxsize if path is None else len(path) - 1

    def subgraph_around(self, node_id: str, radius: int = 2, max_nodes: int = 200,
                        max_edges: int = 500, hub_degree_limit: int = 500) -> dict:
        if not self.node_exists(node_id):
            return {"nodes": [], "edges": []}
        visited: set[str] = {node_id}
        frontier = [node_id]
        truncated = False
        for _ in range(max(radius, 0)):
            if truncated or not frontier:
                break
            preds = self._adjacent_many(frontier, False)
            succs = self._adjacent_many(frontier, True)
            degree = self._degrees_many(nb for n in frontier for nb in (*preds[n], *succs[n]) if nb not in visited)
            next_frontier: list[str] = []
            for node in frontier:
                for nb in (*preds[node], *succs[node]):
                    if nb in visited:
                        continue
                    if degree.get(nb, 0) > hub_degree_limit:
                        continue  # hub node — skip, never expand
                    visited.add(nb)
                    next_frontier.append(nb)
                    if len(visited) >= max_nodes:
                        truncated = True
                        break
                if truncated:
                    break
            frontier = next_frontier

        nodes = []
        for node, data in self._node_attrs_many(visited).items():
            if data.get("type") == "CONCEPT" and node.split("::")[-1] in PYTHON_BUILTINS:
                continue
            data["node_id"] = node
            nodes.append(data)

        edges: list[dict] = []
        members = list(visited)
        for i in range(0, len(members), _CHUNK):
            chunk = members[i:i + _CHUNK]
            for u, v, rel, weight, attrs in self._all(
                    "SELECT src, dst, rel, weight, attrs FROM edges "  # nosec B608
                    f"WHERE src IN ({','.join('?' * len(chunk))})", chunk):
                if v not in visited:
                    continue
                if len(edges) >= max_edges:
                    truncated = True
                    break
                data = self._edge_dict(rel, weight, attrs)
                edge: dict = {"src": u, "dst": v, "rel": data.get("rel", "?"), "weight": data.get("weight", 1.0)}
                if "purpose" in data:
                    edge["purpose"] = data["purpose"]
                edges.append(edge)
            if len(edges) >= max_edges:
                break
        return {"nodes": nodes, "edges": edges, "truncated": truncated}

    # ── integrity (SQL, never materialises the graph) ─────────────────────────

    def integrity_report(self, repo_root: str) -> dict:
        orphans = [r[0] for r in self._all(
            f"SELECT n.id FROM nodes n WHERE n.type IN ('FILE','FUNCTION','CLASS') AND {self._NO_EDGES} "  # nosec B608
            "ORDER BY n.rowid")]
        rels = [r[0] for r in self._all(
            "SELECT id FROM nodes WHERE type='FILE' "
            "UNION SELECT file FROM nodes WHERE type IN ('FUNCTION','CLASS') AND file IS NOT NULL")]
        dangling = [rel for rel in rels if rel and not os.path.exists(os.path.join(repo_root, rel))]
        from datetime import datetime, timezone  # pylint: disable=import-outside-toplevel
        return {
            "orphans": orphans,
            "orphan_stubs": self.orphan_stubs(),
            "dangling_files": dangling,
            "swept_at": datetime.now(tz=timezone.utc).isoformat(),
        }
