# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Knowledge graph for CogniRepo — a directed NetworkX graph tracking relationships
between files, symbols, concepts, queries, and user actions.

Node types  : FILE, FUNCTION, CLASS, CONCEPT, QUERY, SESSION, USER_ACTION
Edge types  : RELATES_TO, DEFINED_IN, CALLED_BY, QUERIED_WITH, CO_OCCURS

Persistence : pickle to .cognirepo/graph/graph.pkl
              On load failure (corruption, version drift, etc.) the unreadable file is
              quarantined to graph.pkl.corrupt-<unix_ts> and an empty graph is started —
              mirrors ast_indexer.py's ast_index.json .corrupt self-heal.
              Exception: an intact but undecryptable (Fernet) file is never quarantined
              and never overwritten — see GraphLockedError (COGNIREPO-97).
Journal     : while indexing, mutations are appended to .cognirepo/graph/graph.journal
              (data/graph/journal.py) every N ops / T seconds; _load() replays it on top of
              graph.pkl and save() compacts it away (COGNIREPO-109). Single writer: only the
              indexer journals (one at a time, via journal.WriterLease); other writers use
              plain save(), which rebases onto newer disk state instead of overwriting it.
Concurrency : every mutation is an op (see _apply) and is remembered in ``_pending`` until
              it is on disk. save() holds store_lock and, if graph.pkl/graph.journal changed
              since this instance last synced, reloads the fresh state and re-applies the
              unsynced ops on top (rebase) — the Git ref-update "compare-and-swap, then redo"
              pattern — so a long-lived watcher can no longer replace a newer index-repo
              result with its stale copy (COGNIREPO-137/139). Mutate through the primitives,
              not ``kg.G`` directly, or the change is invisible to a rebase.
"""
import os
import pickle
import sys
import tempfile
import time
import warnings
from typing import Any

import networkx as nx


from core.config.paths import get_path
from core.config.lock import store_lock
from data.graph import journal as _journal

# Python builtins + common dunder names that must never dominate the concept
# space.  Exported so mcp_server.py can reuse the same set.
PYTHON_BUILTINS: frozenset[str] = frozenset({
    # built-in functions
    "len", "str", "int", "float", "bool", "list", "dict", "set", "tuple",
    "bytes", "bytearray", "memoryview", "complex", "type", "object",
    "range", "enumerate", "zip", "map", "filter", "reversed", "sorted",
    "sum", "min", "max", "abs", "round", "pow", "divmod",
    "open", "print", "input", "repr", "hash", "id", "iter", "next",
    "any", "all", "isinstance", "issubclass", "hasattr", "getattr",
    "setattr", "delattr", "callable", "vars", "dir", "locals", "globals",
    "super", "property", "classmethod", "staticmethod",
    "format", "chr", "ord", "hex", "oct", "bin", "eval", "exec",
    # common list/dict/str methods (added as call nodes by the indexer)
    "append", "extend", "insert", "remove", "pop", "clear", "copy",
    "update", "keys", "values", "items", "get", "setdefault",
    "join", "split", "rsplit", "splitlines", "strip", "lstrip", "rstrip",
    "replace", "startswith", "endswith", "find", "rfind", "index",
    "encode", "decode", "upper", "lower", "capitalize", "title",
    "read", "readline", "readlines", "write", "writelines", "close",
    "seek", "tell", "flush", "fileno",
    # exceptions
    "Exception", "BaseException", "ValueError", "TypeError", "KeyError",
    "IndexError", "AttributeError", "RuntimeError", "StopIteration",
    "GeneratorExit", "OSError", "IOError", "FileNotFoundError",
    "NotImplementedError", "ImportError", "ModuleNotFoundError",
    "OverflowError", "ZeroDivisionError", "MemoryError", "RecursionError",
    "NameError", "UnboundLocalError", "PermissionError", "TimeoutError",
    # dunders
    "__init__", "__new__", "__del__", "__str__", "__repr__", "__bytes__",
    "__len__", "__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__",
    "__hash__", "__bool__", "__iter__", "__next__", "__reversed__",
    "__contains__", "__getitem__", "__setitem__", "__delitem__",
    "__enter__", "__exit__", "__call__", "__get__", "__set__",
    "__add__", "__radd__", "__iadd__", "__sub__", "__mul__", "__truediv__",
    "__class__", "__dict__", "__doc__", "__module__", "__slots__",
    "__all__", "__name__", "__file__", "__spec__", "__path__",
})


# Ops remembered for rebase while no journal is flushing them. Beyond this a long-lived
# writer degrades to last-writer-wins (with a warning) rather than growing without bound.
_UNSYNCED_OPS_CAP = 200_000
_UNSYNCED_COST_CAP = 64 << 20  # estimated bytes (see _op_cost) — bounds attr-heavy ops too

_FERNET_PREFIX = b"gAAAAA"  # every Fernet token starts with version byte 0x80, base64'd


class GraphLockedError(RuntimeError):
    """graph.pkl is encrypted and cannot be decrypted here; saving would destroy it."""


def _graph_file() -> str:
    return get_path("graph/graph.pkl")


def _storage_config() -> tuple[bool, str]:
    from core.security import get_storage_config  # pylint: disable=import-outside-toplevel
    return get_storage_config()


def _op_cost(op: tuple) -> int:
    """Cheap upper-ish estimate of an op's serialized size, used to bound ``_pending`` by
    bytes. Strings/containers count by length; everything else is a flat 8."""
    cost = 64
    for item in op[1:]:
        if isinstance(item, dict):
            for key, val in item.items():
                cost += 16 + len(key) + (len(val) * 24 if isinstance(val, (list, tuple, set, dict))
                                         else len(val) if isinstance(val, (str, bytes)) else 8)
        elif isinstance(item, (str, bytes)):
            cost += len(item)
        else:
            cost += 8
    return cost


def journal_file_exists() -> bool:
    """True when an un-compacted graph.journal is on disk for the active repo."""
    return os.path.exists(_journal_file())


def _journal_file() -> str:
    return get_path("graph/graph.journal")


class NodeType:  # pylint: disable=too-few-public-methods
    """Node types for the knowledge graph."""
    FILE = "FILE"
    FUNCTION = "FUNCTION"
    CLASS = "CLASS"
    CONCEPT = "CONCEPT"
    QUERY = "QUERY"
    SESSION = "SESSION"
    USER_ACTION = "USER_ACTION"
    MEMORY = "MEMORY"          # cross-agent memory nodes (synced from Claude/Gemini/etc.)
    ERROR = "ERROR"            # error pattern nodes for tracking recurring mistakes
    ENDPOINT = "ENDPOINT"      # exposed HTTP/gRPC endpoint (method + path pattern)


class EdgeType:  # pylint: disable=too-few-public-methods
    """Relationship types between nodes."""
    RELATES_TO = "RELATES_TO"
    DEFINED_IN = "DEFINED_IN"
    CALLED_BY = "CALLED_BY"   # caller → callee (forward call direction)
    CALLS = "CALLS"            # callee → caller (reverse; enables BFS to find callers without predecessors())
    QUERIED_WITH = "QUERIED_WITH"
    CO_OCCURS = "CO_OCCURS"
    IMPORTS = "IMPORTS"        # file A imports module/file B
    INHERITS = "INHERITS"      # class A inherits from class B
    EXPOSES = "EXPOSES"        # function → ENDPOINT node (this function handles this route)
    CALLS_ENDPOINT = "CALLS_ENDPOINT"  # caller function → remote ENDPOINT stub (cross-service)
    SIMILAR_TO = "SIMILAR_TO"  # embedding-distance near-duplicate symbols (added both directions)


class KnowledgeGraph:
    """Thin wrapper around a networkx DiGraph with CogniRepo-specific conventions."""

    # Class-level defaults so instances built without __init__ (tests use __new__) behave
    # as "journal off". _pending is a per-instance list created in __init__ (or on first _do).
    _journal_active = False
    _pending: tuple = ()  # replaced by a per-instance list on first use (see _do)
    _journal_seq = 0
    _journal_bytes = 0
    _flush_ops = 5000
    _flush_bytes = 4 << 20
    _pending_cost = 0
    _flush_secs = 30.0
    _last_flush = 0.0
    _locked = False
    _disk_stamp: tuple | None = None
    _lease: "_journal.WriterLease | None" = None
    _pending_overflow = False

    def __init__(self) -> None:
        self.G: nx.DiGraph = nx.DiGraph()  # pylint: disable=invalid-name
        # (mtime_ns, size) of graph.pkl as of the last _load()/save(), plus the
        # path it refers to — _graph_file() is ContextVar-scoped, so the same
        # call inside a _repo_ctx() block names a different repo's graph.
        self._disk_stamp: tuple | None = None
        self._disk_path: str | None = _graph_file()
        # True when graph.pkl is ciphertext we could not decrypt; save() refuses.
        self._locked = False
        # Journal/rebase state (COGNIREPO-109/137/139). _pending = ops not yet on disk: flushed
        # to the journal while begin_journal() is active, otherwise kept so save() can rebase.
        self._journal_active = False
        self._pending: list[tuple] = []
        self._journal_seq = 0          # highest seq applied to / written for this graph
        self._journal_bytes = 0        # journal size this instance knows it has fully applied
        self._flush_ops = 5000
        self._flush_secs = 30.0
        self._last_flush = time.monotonic()
        self._load()

    # ── persistence ───────────────────────────────────────────────────────────

    @staticmethod
    def _stat_stamp(path: str) -> tuple[int, int] | None:
        """Return (mtime_ns, size) for *path*, or None if it does not exist."""
        try:
            st = os.stat(path)
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def reload_if_changed(self) -> bool:
        """Re-read graph.pkl when another process has rewritten it.

        Counterpart to ASTIndexer.reload_if_changed(): the MCP server holds this
        object as a process-lifetime singleton while the watcher mutates the
        graph from a different process, so without revalidation who_calls() and
        subgraph() answer from the graph as it existed at server start.
        Safe against torn reads because save() now promotes via os.replace().
        See COGNIREPO-D-A.
        """
        path = _graph_file()
        if self._disk_path is not None and path != self._disk_path:
            return False  # a _repo_ctx() has repointed get_path() at another repo
        if self._journal_active:
            return False  # this instance is the journal writer; its memory is authoritative
        current = self._full_stamp()
        if current == self._disk_stamp:
            return False
        if self._try_incremental_replay(current):
            return True
        self._rebase()
        return True

    def _rebase(self) -> None:
        """Reload disk state and re-apply this instance's unsynced ops on top of it.

        Replaces "last writer wins" (our whole stale graph over newer disk state) with a
        merge: foreign changes are kept and ours are redone, per attribute. If the unsynced
        log overflowed we cannot redo it, so keep our graph and warn instead.
        """
        ops = self._pending
        if self._pending_overflow:
            warnings.warn(
                "KnowledgeGraph: too many unsaved changes to rebase onto newer on-disk state; "
                "keeping this process's graph (last writer wins).",
                stacklevel=3,
            )
            self._disk_stamp = self._full_stamp()
            return
        self._pending = []
        self._pending_cost = 0
        self._load()  # drops the stale graph, then loads graph.pkl + replays graph.journal
        if self._locked:
            self._pending = ops
            return
        for op in ops:
            self._apply(op)  # not _do(): no auto-flush while save() holds store_lock
        self._pending = ops
        self._pending_cost = sum(_op_cost(o) for o in ops)

    def _try_incremental_replay(self, current: tuple) -> bool:
        """graph.pkl unchanged and the journal only grew: replay just the new segments
        instead of re-unpickling the whole graph on every indexer flush."""
        old = self._disk_stamp
        if (old is None or self._locked or current[0] != old[0]
                or current[1] is None or old[1] is None or self._journal_bytes <= 0):
            return False
        if current[1][1] < self._journal_bytes:
            return False  # journal shrank/was replaced: full reload
        self._replay_journal(start=self._journal_bytes)
        if self._locked:
            return True
        self._disk_stamp = current
        return True

    def _full_stamp(self) -> tuple:
        """Stamp of graph.pkl AND graph.journal — a journal-only append must be seen too."""
        return (self._stat_stamp(_graph_file()), self._stat_stamp(_journal_file()))

    def _load(self) -> None:
        """Load graph.pkl, then replay graph.journal on top of it (COGNIREPO-109)."""
        stamp = self._full_stamp()  # taken BEFORE reading so a concurrent write is re-seen
        # The disk is authoritative on (re)load: drop stale in-memory state and any lock
        # left by an earlier unreadable journal/pickle — _load_base()/replay re-set it.
        self._locked = False
        self.G = nx.DiGraph()
        self._load_base()
        # Seed from the marker pickled inside the graph so segment numbers keep rising
        # across runs even when no journal file exists (COGNIREPO-109 review).
        self._journal_seq = int(self.G.graph.get("journal_seq", 0))
        self._journal_bytes = 0
        if not self._locked:
            self._replay_journal()
        self._disk_stamp = stamp

    def _load_base(self) -> None:
        """Load graph from disk; decrypt if needed."""
        if not os.path.exists(_graph_file()):
            self._disk_stamp = None
            return
        stamp = self._stat_stamp(_graph_file())
        try:
            with open(_graph_file(), "rb") as f:
                raw = f.read()
            from core.security import get_storage_config  # pylint: disable=import-outside-toplevel
            encrypt, project_id = get_storage_config()
            decrypt_error: Exception | None = None
            if encrypt:
                from core.security.encryption import get_or_create_key, decrypt_bytes  # pylint: disable=import-outside-toplevel
                try:
                    raw = decrypt_bytes(raw, get_or_create_key(project_id))
                except Exception as exc:  # pylint: disable=broad-except
                    # The file may have been written unencrypted (e.g. by a
                    # process that resolved the wrong config context before
                    # the _CTX_DIR fix). Fall through and try plaintext —
                    # it will be encrypted on the next save().
                    decrypt_error = exc
            if raw.startswith(_FERNET_PREFIX):
                # Still ciphertext: decryption is unavailable (no keyring in
                # this interpreter) or the key is wrong. The file is intact —
                # do NOT quarantine it (COGNIREPO-97) and do NOT let save()
                # overwrite it with the empty graph we start with here.
                self._locked = True
                self.G = nx.DiGraph()
                self._disk_stamp = stamp
                warnings.warn(
                    f"KnowledgeGraph: {_graph_file()} is encrypted but could not be "
                    f"decrypted ({decrypt_error or 'storage.encrypt is off'}). "
                    "The file was left untouched; starting with an empty in-memory graph "
                    "and refusing to save. Install the security extras in this interpreter "
                    "(pipx inject cognirepo keyring cryptography).",
                    stacklevel=2,
                )
                return
            self._locked = False
            self.G = pickle.loads(raw)  # nosec B301
            self._disk_stamp = stamp
        except Exception as exc:  # pylint: disable=broad-except
            quarantine_path = f"{_graph_file()}.corrupt-{int(time.time())}"
            try:
                os.replace(_graph_file(), quarantine_path)
            except OSError:
                quarantine_path = None
            warnings.warn(
                f"KnowledgeGraph: could not load {_graph_file()} ({exc}). "
                + (
                    f"Quarantined the corrupt file to {quarantine_path}. "
                    if quarantine_path
                    else ""
                )
                + "Starting with an empty graph. Re-run `cognirepo index-repo` to rebuild.",
                stacklevel=2,
            )
            self.G = nx.DiGraph()
            self._disk_stamp = None

    def load(self) -> None:
        """Public alias for reloading the graph from disk."""
        self._load()

    # ── journal (COGNIREPO-109) ────────────────────────────────────────────────

    @staticmethod
    def _journal_key() -> bytes | None:
        encrypt, project_id = _storage_config()
        if not encrypt:
            return None
        from core.security.encryption import get_or_create_key  # pylint: disable=import-outside-toplevel
        return get_or_create_key(project_id)

    def _replay_journal(self, start: int = 0) -> None:
        """Apply journal segments newer than the base pickle's ``journal_seq`` marker.

        Streams one segment at a time (peak = graph + ONE segment, not the whole journal).
        Read-only: a torn tail is ignored here (a reader may be racing the writer's
        in-flight append); the writer truncates it in begin_journal(). If a record turns
        out to be unreadable part-way, the segments before it stay applied, the graph is
        locked and save() refuses — the journal file itself is never touched.
        """
        path = _journal_file()
        if not os.path.exists(path):
            return
        base_seq = self._journal_seq  # marker (full load) or last applied seq (incremental)
        try:
            for seq, ops, end in _journal.iter_segments(path, self._journal_key(), start):
                if seq > base_seq:  # else: already folded into graph.pkl
                    for op in ops:
                        self._apply(op)
                self._journal_seq = max(self._journal_seq, seq)
                self._journal_bytes = end
        except Exception as exc:  # pylint: disable=broad-except
            # Intact but unreadable (wrong/missing key, damaged record). Never delete it
            # and never let save() compact around it.
            self._locked = True
            warnings.warn(
                f"KnowledgeGraph: {path} could not be read ({exc}). The journal was left "
                "untouched and saving is disabled until it is readable again. Restore the "
                "encryption key, or — if its contents are expendable — delete the file and "
                "re-run `cognirepo index-repo`.",
                stacklevel=2,
            )

    def begin_journal(
        self, flush_ops: int = 5000, flush_secs: float = 30.0, flush_bytes: int = 4 << 20,
        wait: float = 0.0,
    ) -> None:
        """Start journaling mutations; call flush_journal()/maybe_flush() to persist them.

        Takes the exclusive writer lease first (raises journal.JournalBusy after ``wait``
        seconds if another process is indexing). A segment is flushed when ANY of
        ``flush_ops``, ``flush_bytes`` (estimated payload size — attrs such as
        ``candidates`` lists vary widely) or ``flush_secs`` is reached, which bounds
        ``_pending`` in addition to the live graph.
        """
        if self._locked:
            raise GraphLockedError("graph is locked; cannot journal")
        path = _journal_file()
        lease = _journal.WriterLease(path)
        lease.acquire(wait)
        try:
            if os.path.exists(path):
                # We hold the lease, so any torn tail is a dead writer's: drop it so new
                # records append after the last intact one, and continue numbering from the
                # on-disk tail. The scan checks only header + crc (no decrypt/unpickle), so
                # the lock is held briefly even on a large journal.
                with store_lock():
                    in_sync = self._full_stamp() == self._disk_stamp
                    good_end, size, tail_seq = _journal.boundary_end(path)
                    if good_end < size:
                        _journal.truncate_to(path, good_end)
                    self._journal_bytes = good_end
                    self._journal_seq = max(self._journal_seq, tail_seq)
                    if in_sync:  # dropping a torn tail changes the stamp, not the content
                        self._disk_stamp = self._full_stamp()
        except BaseException:
            lease.release()
            raise
        self._lease = lease
        self._flush_ops = max(1, int(flush_ops))
        self._flush_bytes = max(1, int(flush_bytes))
        self._flush_secs = float(flush_secs)
        self._last_flush = time.monotonic()
        self._pending_cost = sum(_op_cost(o) for o in self._pending)
        # NB: _pending_overflow is deliberately NOT cleared — ops dropped earlier by the cap
        # are gone from the log, so a rebase must stay disabled until save() resyncs.
        self._journal_active = True

    def end_journal(self) -> None:
        """Flush what is pending and stop journaling."""
        try:
            if self._journal_active:
                self.flush_journal()
        finally:
            # On a failed flush the ops stay in the unsynced log (they are still in self.G
            # and reach disk via save(), which rebases them if disk changed meanwhile).
            self._journal_active = False
            if self._lease is not None:
                self._lease.release()
                self._lease = None

    def flush_journal(self) -> None:
        """Append all pending mutations to the journal as one fsynced segment.

        The sequence number comes from the journal file's tail, read under store_lock —
        never from process memory alone — so two writers can never emit the same seq.
        """
        if not self._pending:
            return
        if self._locked:
            raise GraphLockedError("graph is locked; cannot journal")
        key = self._journal_key()
        path = _journal_file()
        with store_lock():
            in_sync = self._full_stamp() == self._disk_stamp
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            if size != self._journal_bytes:
                # Someone compacted or appended under us. We cannot know that our old
                # offset is still a record boundary in a regrown/replaced file, so rescan
                # from the start (header + crc only — cheap) rather than trust it.
                good_end, _sz, tail_seq = _journal.boundary_end(path, 0)
                if good_end < size:
                    _journal.truncate_to(path, good_end)
                self._journal_bytes = good_end
                self._journal_seq = max(self._journal_seq, tail_seq)
            seq = self._journal_seq + 1
            _journal.append_segment(path, seq, self._pending, key)
            self._journal_bytes = os.path.getsize(path)
            if in_sync:  # our own append must not look like a foreign change
                self._disk_stamp = self._full_stamp()
        self._journal_seq = seq
        self._pending = []
        self._pending_cost = 0
        self._last_flush = time.monotonic()

    def maybe_flush(self) -> None:
        """Flush if enough ops, estimated bytes or time accumulated. Never raises: a
        journal problem must not abort indexing — journaling is switched off and the final
        save() still runs (the journal then holds only what was flushed before the failure)."""
        if not self._journal_active or not self._pending:
            return
        if (len(self._pending) < self._flush_ops
                and self._pending_cost < self._flush_bytes
                and time.monotonic() - self._last_flush < self._flush_secs):
            return
        try:
            self.flush_journal()
        except Exception as exc:  # pylint: disable=broad-except
            # Stop journaling but KEEP the ops: they stay in the unsynced log so the final
            # save() can still rebase them onto newer disk state instead of losing them.
            self._journal_active = False
            if self._lease is not None:
                self._lease.release()
                self._lease = None
            warnings.warn(
                f"KnowledgeGraph: journal flush failed ({exc}); continuing without the "
                "journal — the graph is saved at the end of the run as before.",
                stacklevel=2,
            )

    # ── mutation primitives (live path == replay path) ─────────────────────────

    def _apply(self, op: tuple) -> None:
        """Apply one primitive op. Used by live mutation AND journal replay."""
        kind = op[0]
        if kind == "n":
            _, nid, ntype, attrs = op
            if self.G.has_node(nid):
                self.G.nodes[nid].update(attrs)
            else:
                self.G.add_node(nid, type=ntype, **attrs)
        elif kind == "e":
            _, src, dst, rel, weight, attrs = op
            if self.G.has_edge(src, dst):
                if weight is not None:
                    self.G[src][dst]["weight"] = weight
                self.G[src][dst].update(attrs)
            else:
                data = dict(attrs)
                if rel is not None:
                    data["rel"] = rel
                if weight is not None:
                    data["weight"] = weight
                self.G.add_edge(src, dst, **data)
        elif kind == "na":
            if self.G.has_node(op[1]):
                self.G.nodes[op[1]].update(op[2])
        elif kind == "ea":
            if self.G.has_edge(op[1], op[2]):
                self.G[op[1]][op[2]].update(op[3])
        elif kind == "rn":
            if self.G.has_node(op[1]):
                self.G.remove_node(op[1])
        elif kind == "re":
            if self.G.has_edge(op[1], op[2]):
                self.G.remove_edge(op[1], op[2])
        elif kind == "ga":  # graph-level attribute (G.graph), e.g. the "complete" marker
            self.G.graph[op[1]] = op[2]
        elif kind == "rnd":  # remove node only if still (nearly) unconnected — see prune
            if self.G.has_node(op[1]) and self.G.degree(op[1]) <= op[2]:
                self.G.remove_node(op[1])
        else:
            raise ValueError(f"unknown graph journal op {kind!r}")

    def _do(self, op: tuple) -> None:
        self._apply(op)
        if self._journal_active:
            self._remember(op)
            self._pending_cost += _op_cost(op)
            if len(self._pending) >= self._flush_ops or self._pending_cost >= self._flush_bytes:
                self.maybe_flush()  # bounds segment size inside the post-loop passes too
        elif (len(self._pending) < _UNSYNCED_OPS_CAP
              and self._pending_cost < _UNSYNCED_COST_CAP):
            self._remember(op)  # unsynced log: lets save()/reload rebase, see _rebase()
            self._pending_cost += _op_cost(op)
        else:
            self._pending_overflow = True

    def _remember(self, op: tuple) -> None:
        try:
            self._pending.append(op)
        except AttributeError:  # instance built via __new__ (tests): class default is a tuple
            self._pending = [op]

    def save(self) -> None:
        """Serialize the graph to a pickle file; encrypt if needed.
        Acquires a cross-process file lock to prevent concurrent writes
        from multiple MCP server processes (e.g. Claude + Gemini) from
        corrupting the pickle.
        """
        from data.memory.circuit_breaker import get_breaker  # pylint: disable=import-outside-toplevel
        if self._locked:
            raise GraphLockedError(
                f"{_graph_file()} is encrypted and could not be decrypted in this "
                "interpreter; refusing to overwrite it with an empty graph. "
                "Install keyring + cryptography (pipx inject cognirepo keyring cryptography)."
            )
        breaker = get_breaker()
        breaker.check()
        os.makedirs(os.path.dirname(_graph_file()), exist_ok=True)
        from core.security import get_storage_config  # pylint: disable=import-outside-toplevel
        encrypt, project_id = get_storage_config()
        with store_lock():
            # Compare-and-swap: if graph.pkl / graph.journal changed since we last synced,
            # rebase onto the fresh state instead of overwriting it (COGNIREPO-139).
            if self._disk_stamp is not None and self._full_stamp() != self._disk_stamp:
                self._rebase()
                if self._locked:
                    raise GraphLockedError(
                        f"{_graph_file()} or its journal became unreadable during rebase; "
                        "refusing to save."
                    )
            # Marker pickled WITH the graph: replay skips journal records <= this seq, so a
            # crash between os.replace() below and the journal unlink cannot double-apply.
            # Unflushed ops are already reflected in self.G, hence in this pickle.
            self.G.graph["journal_seq"] = self._journal_seq
            # Atomic promote. A plain open("wb") leaves graph.pkl truncated for
            # the duration of the write, and readers (MCP server revalidation,
            # doctor, a second serve) take no lock — one of them reading mid-write
            # sees a short pickle, fails to unpickle, and quarantines a perfectly
            # good graph as .corrupt-<ts>. os.replace() makes the swap indivisible.
            directory = os.path.dirname(_graph_file()) or "."
            fd, tmp_path = tempfile.mkstemp(
                dir=directory, prefix=os.path.basename(_graph_file()) + ".", suffix=".tmp",
            )
            try:
                if encrypt:
                    # Fernet isn't a streaming cipher — encrypt_bytes() needs the
                    # complete plaintext to compute its MAC, so there is no way to
                    # avoid holding one full serialized copy in memory here (see
                    # COGNIREPO-107 PR discussion). Unavoidable extra buffer is the
                    # graph's own pickle size (single-digit MB on repos tested so
                    # far), not the dominant cost — the cached embedding model was.
                    from core.security.encryption import get_or_create_key, encrypt_bytes  # pylint: disable=import-outside-toplevel
                    raw = pickle.dumps(self.G, protocol=pickle.HIGHEST_PROTOCOL)
                    raw = encrypt_bytes(raw, get_or_create_key(project_id))
                    with os.fdopen(fd, "wb") as f:
                        f.write(raw)
                        f.flush()
                        os.fsync(f.fileno())
                else:
                    # Unencrypted path: stream the pickle straight to disk — no
                    # intermediate in-memory byte buffer of the whole graph.
                    with os.fdopen(fd, "wb") as f:
                        pickle.dump(self.G, f, protocol=pickle.HIGHEST_PROTOCOL)
                        f.flush()
                        os.fsync(f.fileno())
                os.replace(tmp_path, _graph_file())
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            self._compact_journal_locked()
        self._pending = []
        self._pending_cost = 0
        self._pending_overflow = False
        self._disk_stamp = self._full_stamp()
        self._disk_path = _graph_file()
        breaker.record_success()

    def _compact_journal_locked(self) -> None:
        """Drop the journal now that graph.pkl contains it. Caller holds store_lock().

        Only when its size is exactly what this instance applied/wrote — if another
        process appended since, leave it; the journal_seq marker keeps replay correct.
        Note the leftover file lingers until the next save() (or the next writer's
        begin_journal) finds it fully covered by graph.pkl — it is safe, just not tidy.
        """
        path = _journal_file()
        try:
            if os.path.getsize(path) == self._journal_bytes:
                os.unlink(path)
                self._journal_bytes = 0
        except OSError:
            pass

    # ── mutation ──────────────────────────────────────────────────────────────

    def add_node(self, node_id: str, node_type: str, **attrs: Any) -> None:
        """Idempotent add — merges attrs if node already exists."""
        self._do(("n", node_id, node_type, dict(attrs)))

    def add_edge(
        self,
        src: str,
        dst: str,
        edge_type: str,
        weight: float = 1.0,
        **attrs: Any,
    ) -> None:
        """Add a directed edge; if it exists, update its weight."""
        self._do(("e", src, dst, edge_type, weight, dict(attrs)))

    def remove_node(self, node_id: str) -> None:
        """Remove a node and its incident edges (no-op if absent)."""
        self._do(("rn", node_id))

    def remove_node_if_degree_at_most(self, node_id: str, max_degree: int) -> None:
        """Remove a node only if its degree is still <= max_degree when the op is applied.

        For maintenance that selects victims from a possibly stale snapshot (prune): when
        the op is rebased onto newer disk state, a node another writer has since connected
        is kept instead of being destroyed along with the new edges.
        """
        self._do(("rnd", node_id, int(max_degree)))

    def remove_edge(self, src: str, dst: str) -> None:
        """Remove one edge (no-op if absent)."""
        self._do(("re", src, dst))

    def set_node_attrs(self, node_id: str, **attrs: Any) -> None:
        """Merge attrs into an existing node (no-op if absent)."""
        self._do(("na", node_id, dict(attrs)))

    def set_edge_attrs(self, src: str, dst: str, **attrs: Any) -> None:
        """Merge attrs into an existing edge (no-op if absent)."""
        self._do(("ea", src, dst, dict(attrs)))

    # ── completeness (COGNIREPO-122) ──────────────────────────────────────────

    #: ``G.graph`` key stamped by a finished full index. Pickled with the graph.
    COMPLETE_KEY = "complete"

    def mark_complete(self) -> None:
        """Record that a full index built this graph (incremental runs may extend it).

        A journaled op, so the marker survives a full index whose final save() failed
        (the journal replays it) and is re-applied by a rebase."""
        self._do(("ga", self.COMPLETE_KEY, True))

    def incremental_base_status(self, indexed_files: int | None = None) -> tuple[bool, str]:
        """Is this graph a safe base for an incremental (--files / --changed-only / watcher) save?

        An incremental run must never publish a graph that is not a superset of the
        previous one. Returns ``(True, "")`` or ``(False, reason)``.

        * marked complete by a full index → safe;
        * locked (undecryptable) / empty (missing, quarantined, never built or graph
          disabled) → unsafe: saving would replace a full graph with a fragment;
        * unmarked but non-empty (graphs written before the marker existed) → safe only
          if it plausibly covers the indexed repo: at least half as many FILE nodes as the
          AST index has files. A fragment left by an earlier incremental run fails this.
        """
        if self._locked:
            return False, "the graph on disk is encrypted and cannot be decrypted here"
        if self.G.graph.get(self.COMPLETE_KEY):
            return True, ""
        if self.G.number_of_nodes() == 0:
            return False, ("there is no graph on disk (missing, quarantined, never built, "
                           "or disabled for this repo)")
        if not indexed_files:
            return False, "the graph is not marked complete and there is no AST index to verify it against"
        file_nodes = sum(1 for _n, d in self.G.nodes(data=True) if d.get("type") == NodeType.FILE)
        if file_nodes * 2 < indexed_files:
            return False, (f"the graph covers {file_nodes} files but the AST index has "
                           f"{indexed_files} — it looks like a fragment, not a full graph")
        return True, ""

    def remove_node_edges(self, node_id: str) -> None:
        """Remove all edges incident to node_id (but keep the node)."""
        edges = list(self.G.in_edges(node_id)) + list(self.G.out_edges(node_id))
        for src, dst in edges:
            self.remove_edge(src, dst)

    def nodes_for_file(self, file_path: str) -> list[str]:
        """Return all node IDs whose stored 'file' attr matches file_path."""
        return [
            n for n, d in self.G.nodes(data=True) if d.get("file") == file_path
        ]

    def remove_file_nodes(self, file_path: str) -> list[str]:
        """Remove all nodes (and their incident edges) associated with file_path.

        Removes:
        - Symbol/function/class nodes whose 'file' attribute == file_path
        - The FILE node whose node_id == file_path (convention from make_node_id)

        Before a FUNCTION/CLASS node is dropped, any live call/inherit edges it
        participates in are preserved onto a `symbol::{name}` CONCEPT stub (see
        `_redirect_edges_to_stub`) rather than silently discarded by NetworkX's
        automatic incident-edge removal — COGNIREPO-D10. A later
        `ASTIndexer._resolve_call_stubs()` pass reconciles the stub: merges it
        back into a real node if one still exists elsewhere, or leaves it
        correctly tagged `unresolved=True` if the symbol is genuinely gone.

        Returns the list of removed node IDs.
        """
        removed: list[str] = []
        for nid in self.nodes_for_file(file_path):
            if self.G.has_node(nid):
                self._redirect_edges_to_stub(nid)
                self.remove_node(nid)
                removed.append(nid)
        # FILE node's node_id == rel_path (see make_node_id("FILE", name) → name)
        if self.G.has_node(file_path):
            self.remove_node(file_path)
            removed.append(file_path)
        return removed

    def _redirect_edges_to_stub(self, nid: str) -> None:
        """
        Preserve a FUNCTION/CLASS node's call/inherit edges onto a
        `symbol::{name}` CONCEPT stub before the node itself is removed.

        Without this, deleting a symbol that still has live callers (CALLED_BY
        predecessors) or an inheriting subclass (INHERITS predecessors) would
        silently drop those edges when NetworkX removes the node's incident
        edges — the callers' own unchanged AST records still say they call/
        inherit from it, so that information is real and worth keeping
        discoverable via `who_calls`/`subgraph`, tagged as unresolved rather
        than deleted outright. Mirrors `_resolve_call_stubs()`'s edge-copy
        pattern in reverse. See COGNIREPO-D10.
        """
        node_data = self.G.nodes.get(nid, {})
        if node_data.get("type") not in (NodeType.FUNCTION, NodeType.CLASS):
            return  # only symbol nodes participate in call/inherit stub edges

        predecessors = list(self.G.predecessors(nid))
        successors = list(self.G.successors(nid))
        if not predecessors and not successors:
            return  # nothing referenced this node — safe to just drop it

        name = nid.rsplit("::", 1)[-1]
        stub = f"symbol::{name}"
        if stub == nid:
            return  # node IS the stub (shouldn't happen for a file-scoped node)
        self.add_node(stub, NodeType.CONCEPT, unresolved=True)

        for pred in predecessors:
            if pred == stub:
                continue
            if not self.G.has_edge(pred, stub):
                self.copy_edge(pred, nid, pred, stub)
        for succ in successors:
            if succ == stub:
                continue
            if not self.G.has_edge(stub, succ):
                self.copy_edge(nid, succ, stub, succ)

    def copy_edge(self, src: str, dst: str, new_src: str, new_dst: str) -> None:
        """Re-create edge (src, dst) as (new_src, new_dst) with identical attributes."""
        data = dict(self.G[src][dst])
        rel = data.pop("rel", None)
        weight = data.pop("weight", None)
        self._do(("e", new_src, new_dst, rel, weight, data))

    # ── queries ───────────────────────────────────────────────────────────────

    def node_exists(self, node_id: str) -> bool:
        """Return True if node_id is present in the graph."""
        return self.G.has_node(node_id)

    def get_neighbours(
        self,
        node_id: str,
        depth: int = 1,
        edge_type: str | None = None,
    ) -> list[dict]:
        """
        BFS up to `depth` hops from node_id.
        Optionally filter by edge rel type.
        Returns list of {"node_id", "type", "hops", ...node_attrs}.
        """
        if not self.G.has_node(node_id):
            return []

        from collections import deque  # pylint: disable=import-outside-toplevel
        visited: dict[str, int] = {node_id: 0}
        queue: deque[str] = deque([node_id])
        results: list[dict] = []

        while queue:
            current = queue.popleft()
            current_hops = visited[current]
            if current_hops >= depth:
                continue
            for neighbor in self.G.successors(current):
                if neighbor in visited:
                    continue
                edge_data = self.G[current][neighbor]
                if edge_type and edge_data.get("rel") != edge_type:
                    continue
                hops = current_hops + 1
                visited[neighbor] = hops
                node_data = dict(self.G.nodes[neighbor])
                node_data["node_id"] = neighbor
                node_data["hops"] = hops
                results.append(node_data)
                queue.append(neighbor)

        return results

    def hop_distance(self, src: str, dst: str) -> int:
        """Shortest hop distance; sys.maxsize if no path or either node missing."""
        if not self.G.has_node(src) or not self.G.has_node(dst):
            return sys.maxsize
        try:
            return nx.shortest_path_length(self.G, src, dst)
        except nx.NetworkXNoPath:
            return sys.maxsize

    def shortest_path(self, src: str, dst: str) -> list[str] | None:
        """Returns node list of shortest path, or None if no path."""
        try:
            return nx.shortest_path(self.G, src, dst)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def subgraph_around(
        self,
        node_id: str,
        radius: int = 2,
        max_nodes: int = 200,
        max_edges: int = 500,
        hub_degree_limit: int = 500,
    ) -> dict:
        """
        Returns {"nodes": [...], "edges": [...], "truncated": bool} of the
        neighbourhood around node_id, bounded DURING expansion.

        Previously this used nx.ego_graph(), which materializes the full
        ego graph before any cap is applied — on syscall-heavy repos a
        depth-3 call could pull 10k+ nodes and inflate RSS past the circuit
        breaker limit. The bounded BFS stops at max_nodes and skips hub
        nodes whose degree exceeds hub_degree_limit (e.g. errnoErr/uintptr
        fan-out), which are connectivity noise rather than architecture.
        """
        if not self.G.has_node(node_id):
            return {"nodes": [], "edges": []}

        visited: set[str] = {node_id}
        frontier: list[str] = [node_id]
        truncated = False
        for _ in range(max(radius, 0)):
            if truncated or not frontier:
                break
            next_frontier: list[str] = []
            for n in frontier:
                for nb in nx.all_neighbors(self.G, n):
                    if nb in visited:
                        continue
                    if self.G.degree(nb) > hub_degree_limit:
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
        for n in visited:
            d = self.G.nodes[n]
            # Skip builtin names — they add noise, not signal, to neighbourhoods
            bare = n.split("::")[-1]
            if d.get("type") == "CONCEPT" and bare in PYTHON_BUILTINS:
                continue
            entry = dict(d)
            entry["node_id"] = n
            nodes.append(entry)

        edges = []
        for u, v, d in self.G.edges(visited, data=True):
            if v not in visited:
                continue
            if len(edges) >= max_edges:
                truncated = True
                break
            edge: dict = {
                "src": u, "dst": v,
                "rel": d.get("rel", "?"),
                "weight": d.get("weight", 1.0),
            }
            if "purpose" in d:
                edge["purpose"] = d["purpose"]
            edges.append(edge)

        return {"nodes": nodes, "edges": edges, "truncated": truncated}

    # ── stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return basic node and edge counts."""
        return {
            "nodes": self.G.number_of_nodes(),
            "edges": self.G.number_of_edges(),
        }

    # ── integrity ─────────────────────────────────────────────────────────────

    _ORPHAN_TYPES = (NodeType.FILE, NodeType.FUNCTION, NodeType.CLASS)

    def integrity_report(self, repo_root: str) -> dict:
        """Structural + on-disk integrity sweep. O(nodes) — safe to run on every
        graph_stats call (AC4: < 1s on a medium repo).

        orphans        : FILE/FUNCTION/CLASS node IDs with degree 0. Restricted to
                          these types — MEMORY/SESSION/ERROR/QUERY/USER_ACTION/CONCEPT
                          nodes are legitimately edge-free early in their lifecycle.
        dangling_files : unique file paths (FILE node IDs, or FUNCTION/CLASS nodes'
                          'file' attr) that no longer exist under repo_root — left
                          behind when a file is deleted outside a live watcher/server
                          (COGNIREPO-100-Discovery §3/§4).
        swept_at       : ISO-8601 UTC timestamp of this sweep.

        See COGNIREPO-201.
        """
        orphans = [
            n for n, d in self.G.nodes(data=True)
            if d.get("type") in self._ORPHAN_TYPES and self.G.degree(n) == 0
        ]

        dangling: list[str] = []
        checked: set[str] = set()
        for n, d in self.G.nodes(data=True):
            ntype = d.get("type")
            if ntype == NodeType.FILE:
                rel = n
            elif ntype in (NodeType.FUNCTION, NodeType.CLASS):
                rel = d.get("file")
            else:
                continue
            if not rel or rel in checked:
                continue
            checked.add(rel)
            if not os.path.exists(os.path.join(repo_root, rel)):
                dangling.append(rel)

        from datetime import datetime, timezone  # pylint: disable=import-outside-toplevel
        return {
            "orphans": orphans,
            "dangling_files": dangling,
            "swept_at": datetime.now(tz=timezone.utc).isoformat(),
        }
