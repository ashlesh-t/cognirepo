# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""
vector_db/factory.py
Reads storage.vector_backend from .cognirepo/config.json and returns
the appropriate VectorStorageAdapter implementation.
Defaults to "chroma" (ChromaDB) for semantic text storage.
FAISS is always used separately for AST indexing (via ast_indexer.py).

Opening a chroma store safely (COGNIREPO-142)
---------------------------------------------
A poisoned store can SEGFAULT the opening process inside chromadb's Rust core (observed: chromadb
1.5.8 infinite recursion in Collection.count() on a 200MB store). That can't be caught in-process,
but the dead process leaves a per-process sentinel behind as crash evidence for the NEXT one. The
old logic quarantined (renamed) the whole store whenever a sentinel's pid was dead — which also
happens when an opener was merely *killed* (OOM, hook timeout, Ctrl-C), and even while a peer had
the healthy store open. It is now:

* per-process sentinels ``.opening.<pid>`` (one shared file let one opener erase another's
  evidence), plus ``.open.<pid>`` markers that live as long as a process has the store open;
* a marker/sentinel is "live" only if the pid exists AND has the same start time (pid reuse);
* quarantine happens only under the store lock, only if no live peer has the store open, and only
  if a throw-away subprocess **fails to open it** — a store that opens fine is never renamed.
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from core.config.atomic import atomic_write
from core.config.lock import store_lock
from core.config.paths import get_cognirepo_dir
from core.vector_db.adapter import VectorStorageAdapter

_log = logging.getLogger(__name__)

_SENTINEL_PREFIX = ".opening."     # present only while a process is inside ChromaDBAdapter()
_MARKER_PREFIX = ".open."          # present while a process holds the store open
_PROBE_TIMEOUT = 180.0
_HEAL_LOCK_TIMEOUT = 300.0

_PROBE_CODE = (
    "import sys, chromadb\n"
    "c = chromadb.PersistentClient(path=sys.argv[1])\n"
    "for col in c.list_collections():\n"
    "    c.get_collection(col.name if hasattr(col, 'name') else col).count()\n"
)


# ── process identity ──────────────────────────────────────────────────────────

def _proc_start(pid: int) -> "str | None":
    """Start time of ``pid`` (clock ticks since boot, /proc field 22); None if unknowable."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            return fh.read().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def _pid_alive(pid: int) -> bool:
    """Running process? A zombie (exited, un-reaped) is not alive."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True          # exists, owned by someone else
    except (OSError, ValueError):
        return False
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def _record(pid: "int | None" = None) -> dict:
    pid = pid or os.getpid()
    return {"pid": pid, "start": _proc_start(pid), "ts": time.time()}


def _is_live(rec: dict) -> bool:
    """The recorded process still exists AND is the same process (guards against pid reuse)."""
    pid = rec.get("pid")
    if not isinstance(pid, int) or not _pid_alive(pid):
        return False
    start = rec.get("start")
    current = _proc_start(pid)
    return start is None or current is None or start == current


def _read_records(store: Path, prefix: str) -> "list[tuple[Path, dict]]":
    out = []
    try:
        names = sorted(n for n in os.listdir(store) if n.startswith(prefix))
    except OSError:
        return out
    for name in names:
        path = store / name
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(rec, dict):
                raise ValueError("not a record")
        except (OSError, ValueError):
            rec = {}          # unreadable/legacy (a bare pid) record: treat as dead evidence
            try:
                legacy = int(path.read_text(encoding="utf-8").strip())
                rec = {"pid": legacy, "start": None}
            except (OSError, ValueError):
                pass
        out.append((path, rec))
    return out


def _write_record(store: Path, name: str) -> "Path | None":
    path = store / name
    try:
        store.mkdir(parents=True, exist_ok=True)
        atomic_write(str(path), json.dumps(_record()), fsync=False)  # evidence file, not a store
        return path
    except OSError:
        return None


def _remove(path: "Path | None") -> None:
    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


# Markers this process created; removed at exit so a clean shutdown leaves no trace. A process
# that is killed leaves a marker whose pid is dead — harmless: dead markers are ignored.
_MY_MARKERS: "list[Path]" = []
_ATEXIT_REGISTERED = False


def _register_open_marker(store: Path) -> None:
    global _ATEXIT_REGISTERED  # pylint: disable=global-statement
    marker = _write_record(store, f"{_MARKER_PREFIX}{os.getpid()}")
    if marker is not None and marker not in _MY_MARKERS:
        _MY_MARKERS.append(marker)
    if not _ATEXIT_REGISTERED:
        atexit.register(lambda: [_remove(m) for m in list(_MY_MARKERS)])
        _ATEXIT_REGISTERED = True


# ── quarantine ────────────────────────────────────────────────────────────────

def quarantine_chroma_store(path: Path | None = None) -> str | None:
    """Rename a poisoned chroma store aside (kept, not deleted). Returns new path."""
    store = Path(path) if path else _get_vector_db_path()
    if not store.exists():
        return None
    dest = store.with_name(f"chroma.corrupt-{int(time.time())}")
    try:
        store.rename(dest)
    except OSError as exc:
        _log.warning("could not quarantine chroma store %s: %s", store, exc)
        return None
    # chromadb caches one client per path inside the process; after the rename that cached client
    # still points at the quarantined directory, and the next PersistentClient(path) would hand it
    # back instead of opening a fresh store. A long-lived server hits this on its next open.
    try:
        from chromadb.api.client import SharedSystemClient  # pylint: disable=import-outside-toplevel
        SharedSystemClient.clear_system_cache()
    except Exception:  # pylint: disable=broad-except
        pass
    return str(dest)


def _probe_store(path: Path) -> bool:
    """Can a fresh process open the store and count every collection? (read-only)

    Run in a SUBPROCESS: a poisoned store crashes the opener natively, which must not take
    this process down. True = opens fine (healthy); False = crashed, errored or timed out.
    """
    try:
        res = subprocess.run(
            [sys.executable, "-c", _PROBE_CODE, str(path)],
            capture_output=True, timeout=_PROBE_TIMEOUT, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return res.returncode == 0


def _heal_crashed_chroma(path: Path) -> None:
    """Decide what a dead opener's sentinel means — quarantining only a store that is really bad."""
    if not path.exists() or not _read_records(path, _SENTINEL_PREFIX):
        return
    from core.vector_db.chroma_adapter import chroma_lock_path  # pylint: disable=import-outside-toplevel
    with store_lock(timeout=_HEAL_LOCK_TIMEOUT, lock_path=chroma_lock_path(str(path))):
        sentinels = _read_records(path, _SENTINEL_PREFIX)
        dead = [(p, r) for p, r in sentinels if not _is_live(r)]
        if not dead:
            return                    # every sentinel belongs to a live opener right now
        live_peers = [
            r.get("pid") for _p, r in
            _read_records(path, _SENTINEL_PREFIX) + _read_records(path, _MARKER_PREFIX)
            if _is_live(r) and r.get("pid") != os.getpid()
        ]
        if live_peers:
            _log.warning(
                "chroma store %s has a stale open sentinel (a previous opener died) but live "
                "process(es) %s have it open — NOT quarantining.", path, live_peers)
            for p, _r in dead:
                _remove(p)
            return
        if _probe_store(path):
            _log.warning(
                "a previous process died while opening the chroma store at %s, but a fresh open "
                "succeeds — it was killed, not poisoned. Keeping the store.", path)
            for p, _r in dead:
                _remove(p)
            return
        _log.warning(
            "A previous process crashed while opening the chroma store at %s and it still fails "
            "to open (native chromadb fault). Quarantining it and starting fresh — the old store "
            "is kept as chroma.corrupt-<timestamp>.", path)
        quarantine_chroma_store(path)


# ── factory ───────────────────────────────────────────────────────────────────

def get_vector_adapter(
    dim: int = 384,
    *,
    breaker_factory=None,
    cleanup_queue_factory=None,
) -> VectorStorageAdapter:
    """Return FAISS or ChromaDB adapter based on config.json storage.vector_backend.

    breaker_factory / cleanup_queue_factory — forwarded to LocalVectorDB only
    (the faiss backend); ChromaDBAdapter has no circuit-breaker/cleanup-queue
    integration. See COGNIREPO-D06.
    """
    backend = _read_backend()
    if backend == "chroma":
        try:
            from core.vector_db.chroma_adapter import ChromaDBAdapter  # pylint: disable=import-outside-toplevel
            path = _get_vector_db_path()
            _log.debug("vector backend: chroma at %s", path)
            _heal_crashed_chroma(path)
            # Per-process sentinel: crash evidence that no other opener can overwrite or erase.
            # Removed on ANY return/exception from the constructor; only a native crash (which
            # skips this finally) leaves it behind.
            sentinel = _write_record(path, f"{_SENTINEL_PREFIX}{os.getpid()}")
            try:
                adapter = ChromaDBAdapter(path=str(path))
            finally:
                _remove(sentinel)
            _register_open_marker(path)
            return adapter
        except ImportError:
            _log.warning(
                "chromadb not installed — falling back to faiss. "
                "Run: pip install chromadb"
            )
    _log.debug("vector backend: faiss")
    from core.vector_db.local_vector_db import LocalVectorDB  # pylint: disable=import-outside-toplevel
    return LocalVectorDB(
        dim=dim,
        breaker_factory=breaker_factory,
        cleanup_queue_factory=cleanup_queue_factory,
    )


def _read_backend() -> str:
    try:
        config_path = _find_config()
        if config_path and config_path.exists():
            data = json.loads(config_path.read_text(encoding="utf-8"))
            return data.get("storage", {}).get("vector_backend", "chroma")
    except Exception:  # pylint: disable=broad-except
        pass
    return "chroma"


def _find_config() -> Path | None:
    """The active repo's config.json, resolved exactly like every other store.

    Previously this walked up from the cwd looking for ``.cognirepo/config.json``, so a process
    started in a subdirectory (or with ``COGNIREPO_DIR`` set, as the MCP ``serve`` process is)
    could open a different chroma store than the rest of cognirepo — and with no config at all it
    silently fell back to ``~/.cognirepo`` (a test was opening the real home store).
    """
    candidate = Path(get_cognirepo_dir()) / "config.json"
    return candidate if candidate.exists() else None


def _get_vector_db_path() -> Path:
    config = _find_config()
    base = config.parent if config else Path(get_cognirepo_dir())
    return base / "vector_db" / "chroma"
