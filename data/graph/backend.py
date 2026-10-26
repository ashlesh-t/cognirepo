# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Which store backs ``KnowledgeGraph()`` for this repo (#115, ADR 002).

``storage.graph_backend`` in ``.cognirepo/config.json`` is ``"networkx"`` (default: the graph is a
pickle loaded whole into every process) or ``"sqlite"`` (a WAL database read on demand, see
``sqlite_graph.py``). Opt-in: nothing changes unless a repo asks for it.

``storage.encrypt: true`` always selects networkx. A SQLite file is not covered by the Fernet
encryption that protects ``graph.pkl`` and its journal (ADR 002 §7, #186), so honouring ``sqlite``
there would silently drop a security promise; :func:`resolve` says so instead.

``COGNIREPO_GRAPH_BACKEND`` overrides the config file (tests, CI, a one-off benchmark); the
encryption rule still wins over it.
"""
from __future__ import annotations

import json
import os
import warnings
from typing import NamedTuple

NETWORKX = "networkx"
SQLITE = "sqlite"
BACKENDS = (NETWORKX, SQLITE)
ENV_VAR = "COGNIREPO_GRAPH_BACKEND"


class Resolution(NamedTuple):
    """The backend in force and, when it differs from what was asked for, why."""
    backend: str
    requested: str
    note: str = ""


def _config(store: str | None = None) -> dict:
    """``config.json`` of *store* (a ``.cognirepo`` directory), or of the repo the context points at."""
    if store is None:
        from core.config.paths import get_path  # pylint: disable=import-outside-toplevel
        path = get_path("config.json")
    else:
        path = os.path.join(store, "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def env_override() -> str:
    """The backend forced by ``COGNIREPO_GRAPH_BACKEND`` in THIS process ("" when unset)."""
    return os.environ.get(ENV_VAR, "").strip().lower()


def configured(store: str | None = None) -> str:
    """``storage.graph_backend`` as written in the config file (default networkx); the env override is ignored."""
    storage = _config(store).get("storage")
    value = storage.get("graph_backend", NETWORKX) if isinstance(storage, dict) else NETWORKX
    return str(value).strip().lower() or NETWORKX


def encryption_on(store: str | None = None) -> bool:
    if store is None:
        from core.security import get_storage_config  # pylint: disable=import-outside-toplevel
        return bool(get_storage_config()[0])
    storage = _config(store).get("storage")
    return bool(isinstance(storage, dict) and storage.get("encrypt", False))


def resolve(store: str | None = None) -> Resolution:
    """Backend in force for *store* (default: the repo the current context points at). Cheap enough to call
    per construction."""
    requested = env_override() or configured(store)
    if requested not in BACKENDS:
        warnings.warn(
            f"storage.graph_backend {requested!r} is not one of {BACKENDS}; using {NETWORKX}.",
            stacklevel=2,
        )
        return Resolution(NETWORKX, requested, f"unknown backend {requested!r}")
    if requested == SQLITE and encryption_on(store):
        return Resolution(
            NETWORKX, SQLITE,
            "storage.encrypt is on: the SQLite graph file is not encrypted yet (#186), "
            "so the encrypted pickle graph stays in use",
        )
    return Resolution(requested, requested)


def graph_store_path() -> str:
    """The on-disk file that holds the graph under the backend in force (for "is there a graph?" checks)."""
    from core.config.paths import get_path  # pylint: disable=import-outside-toplevel
    return get_path("graph/graph.sqlite" if resolve().backend == SQLITE else "graph/graph.pkl")


def is_current(graph: object) -> bool:
    """False when *graph* was built for a backend that is no longer the one in force. Long-lived holders
    (the MCP server's singleton, UI caches) rebuild when this turns False, so a backend switch reaches running
    agents on their next call instead of leaving them writing to the old store."""
    is_sqlite = type(graph).__name__ == "SqliteGraph"      # by name: survives a reloaded module
    return is_sqlite == (resolve().backend == SQLITE)


def _file_info(*paths: str) -> dict:
    size, newest, found = 0, 0.0, False
    for path in paths:
        try:                                   # stat once: a file can vanish between exists() and getsize()
            st = os.stat(path)
        except OSError:
            continue
        found, size, newest = True, size + st.st_size, max(newest, st.st_mtime)
    return {"exists": found, "bytes": size, "mtime": newest if found else None}


def graph_files(store: str) -> dict:
    """Existence, size and newest mtime of each backend's file(s) under *store* (SQLite includes its WAL)."""
    g = os.path.join(store, "graph")
    db = os.path.join(g, "graph.sqlite")
    return {NETWORKX: _file_info(os.path.join(g, "graph.pkl")),
            SQLITE: _file_info(db, db + "-wal")}


SYNC_FILE = "backend_sync.json"


def _sync_path(store: str) -> str:
    return os.path.join(store, "graph", SYNC_FILE)


def mark_synced(store: str) -> None:
    """Record that the two stores hold the same graph right now (written after a verified migration), as each
    file's mtime. Without it "the other file is newer" cannot tell *changed since the copy* from *simply copied
    later than the source was written*."""
    from core.config.atomic import atomic_json_dump  # pylint: disable=import-outside-toplevel
    files = graph_files(store)
    try:
        atomic_json_dump(_sync_path(store), {n: files[n]["mtime"] for n in BACKENDS}, indent=None, fsync=False)
    except OSError:
        pass


def _synced_mtimes(store: str) -> dict | None:
    try:
        with open(_sync_path(store), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def changed_since_sync(store: str, name: str) -> bool:
    """True when backend *name*'s file has been written to since the stores were last known to match.

    With a sync record (any verified migration) that is exact. Without one (a graph imported on first open) it
    falls back to "this file is newer than the other one"."""
    files = graph_files(store)
    if not files[name]["exists"]:
        return False
    marker = _synced_mtimes(store)
    if marker and isinstance(marker.get(name), (int, float)):
        return files[name]["mtime"] > marker[name] + 1
    other = SQLITE if name == NETWORKX else NETWORKX
    return files[other]["exists"] and files[name]["mtime"] > files[other]["mtime"] + 1


def stale_note(store: str | None = None) -> str:
    """Why the graph in use may be out of date relative to the other backend's file, or "".

    The pickle is imported into SQLite once and kept as the fallback, but nothing syncs them afterwards: if
    both files exist and the one NOT in use has been written since they last matched, the changes made under
    the other backend are invisible to this one."""
    if store is None:
        from core.config.paths import get_cognirepo_dir  # pylint: disable=import-outside-toplevel
        store = str(get_cognirepo_dir())
    files, active = graph_files(store), resolve(store).backend
    if not (files[NETWORKX]["exists"] and files[SQLITE]["exists"]):
        return ""
    if active == SQLITE and changed_since_sync(store, NETWORKX):
        return ("graph.pkl is newer than graph.sqlite: changes made while the networkx backend was in use are "
                "not in the SQLite graph (the pickle is imported only once). Re-run `cognirepo index-repo .`, or "
                "delete graph.sqlite to import the pickle again")
    if active == NETWORKX and changed_since_sync(store, SQLITE):
        return ("graph.sqlite is newer than graph.pkl: changes made while the SQLite backend was in use are not "
                "in the pickle graph. Re-run `cognirepo index-repo .` to rebuild it")
    return ""


switch_note = stale_note        # name used by `doctor` since #239


def needs_migration(store: str, to: str) -> bool:
    """True when switching *to* would put the repo on a graph that is missing or older than the other one's
    (i.e. a bare config flip would show stale or no data); False when the target is up to date."""
    files = graph_files(store)
    other = NETWORKX if to == SQLITE else SQLITE
    if not files[other]["exists"]:
        return False                      # nothing to carry over: the target builds itself on the next index
    if not files[to]["exists"]:
        return True
    return changed_since_sync(store, other)


def graph_counts(store: str) -> tuple[int, int] | None:
    """(nodes, edges) from the ``graph.stats`` sidecar written on every save; None if it was never written."""
    from data.graph import graph_seq  # pylint: disable=import-outside-toplevel
    stats = graph_seq.read_stats(store)
    return None if stats is None else (stats["nodes"], stats["edges"])


# ── when to use which ──────────────────────────────────────────────────────────
# Thresholds come from ONE synthetic benchmark (scripts/bench_graph_backends.py: ~4 KB resident per node per
# process on networkx, ~5x less on sqlite at 100k nodes, queries ~4-10x slower). They are advice, not rules.
NODES_LARGE = 100_000
NODES_MEDIUM = 20_000
SESSIONS_MANY = 3
KB_PER_NODE = 4.4


class Recommendation(NamedTuple):
    use: str            # "networkx" | "sqlite"
    confidence: str     # "clear" | "leaning" | "either"
    reasons: list[str]


def recommend(nodes: int | None, sessions: int, encrypted: bool) -> Recommendation:
    """Which backend to use, with the reasons (shown verbatim in the console)."""
    if encrypted:
        return Recommendation(NETWORKX, "clear", [
            "storage.encrypt is on and the SQLite graph file is not encrypted yet (#186), so networkx is required"])
    if nodes is None:
        return Recommendation(NETWORKX, "either", [
            "the graph size is not known yet (index the repo first); networkx is the default and fine for most repos"])
    mb = nodes * KB_PER_NODE / 1024
    if nodes >= NODES_LARGE:
        return Recommendation(SQLITE, "clear", [
            f"{nodes:,} nodes: each cognirepo process holds about {mb:,.0f} MB of graph on networkx, versus a "
            "fraction of that on sqlite (measured: 459 MB vs 54-92 MB at 105k nodes)",
            "sqlite opens instantly and saves only what changed; queries cost milliseconds instead of microseconds"])
    if nodes >= NODES_MEDIUM and sessions >= SESSIONS_MANY:
        return Recommendation(SQLITE, "leaning", [
            f"{sessions} cognirepo processes on this repo each hold a full copy of a {nodes:,}-node graph "
            f"(about {mb * sessions:,.0f} MB together) on networkx; sqlite shares one file"])
    if nodes >= NODES_MEDIUM:
        return Recommendation(NETWORKX, "either", [
            f"{nodes:,} nodes is mid-sized: networkx costs about {mb:,.0f} MB per process but answers queries fastest; "
            "choose sqlite if memory is tight or several agents will share this repo"])
    return Recommendation(NETWORKX, "clear", [
        f"only {nodes:,} nodes: networkx is the fastest and the smallest on disk, and the memory it uses "
        f"(about {mb:,.0f} MB) is small"])


def graph_class() -> type:
    """The ``KnowledgeGraph`` subclass to instantiate (the base class itself for networkx)."""
    if resolve().backend == SQLITE:
        from data.graph.sqlite_graph import SqliteGraph  # pylint: disable=import-outside-toplevel
        return SqliteGraph
    from data.graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
    return KnowledgeGraph
