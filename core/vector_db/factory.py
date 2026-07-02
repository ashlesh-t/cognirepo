# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""
vector_db/factory.py
Reads storage.vector_backend from .cognirepo/config.json and returns
the appropriate VectorStorageAdapter implementation.
Defaults to "chroma" (ChromaDB) for semantic text storage.
FAISS is always used separately for AST indexing (via ast_indexer.py).
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from core.vector_db.adapter import VectorStorageAdapter

_log = logging.getLogger(__name__)

# Sentinel written while a process is opening the chroma store. A poisoned
# store can SEGFAULT the opening process inside chromadb's Rust core
# (observed: chromadb 1.5.8 infinite recursion in Collection.count() on a
# 200MB store) — that cannot be caught in-process, but the dead process
# leaves this sentinel behind as crash evidence for the NEXT process.
_OPEN_SENTINEL = ".opening"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def quarantine_chroma_store(path: Path | None = None) -> str | None:
    """Rename a poisoned chroma store aside (kept, not deleted). Returns new path."""
    store = Path(path) if path else _get_vector_db_path()
    if not store.exists():
        return None
    dest = store.with_name(f"chroma.corrupt-{int(time.time())}")
    try:
        store.rename(dest)
        return str(dest)
    except OSError as exc:
        _log.warning("could not quarantine chroma store %s: %s", store, exc)
        return None


def _heal_crashed_chroma(path: Path) -> None:
    """Quarantine the store if a previous process died while opening it."""
    sentinel = path / _OPEN_SENTINEL
    if not sentinel.exists():
        return
    try:
        pid = int(sentinel.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        pid = 0
    if pid and _pid_alive(pid):
        return  # another process is opening the store right now — not a crash
    _log.warning(
        "A previous process crashed while opening the chroma store at %s "
        "(native chromadb fault). Quarantining it and starting fresh — the old "
        "store is kept as chroma.corrupt-<timestamp>.", path,
    )
    quarantine_chroma_store(path)


def get_vector_adapter(dim: int = 384) -> VectorStorageAdapter:
    """Return FAISS or ChromaDB adapter based on config.json storage.vector_backend."""
    backend = _read_backend()
    if backend == "chroma":
        try:
            from core.vector_db.chroma_adapter import ChromaDBAdapter  # pylint: disable=import-outside-toplevel
            path = _get_vector_db_path()
            _log.debug("vector backend: chroma at %s", path)
            _heal_crashed_chroma(path)
            sentinel = path / _OPEN_SENTINEL
            try:
                path.mkdir(parents=True, exist_ok=True)
                sentinel.write_text(str(os.getpid()), encoding="utf-8")
            except OSError:
                pass
            adapter = ChromaDBAdapter(path=str(path))
            try:
                sentinel.unlink(missing_ok=True)
            except OSError:
                pass
            return adapter
        except ImportError:
            _log.warning(
                "chromadb not installed — falling back to faiss. "
                "Run: pip install chromadb"
            )
    _log.debug("vector backend: faiss")
    from core.vector_db.local_vector_db import LocalVectorDB  # pylint: disable=import-outside-toplevel
    return LocalVectorDB(dim=dim)


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
    """Walk up from cwd to find .cognirepo/config.json."""
    for parent in [Path.cwd(), *Path.cwd().parents]:
        candidate = parent / ".cognirepo" / "config.json"
        if candidate.exists():
            return candidate
    return None


def _get_vector_db_path() -> Path:
    config = _find_config()
    base = config.parent / "vector_db" if config else Path.home() / ".cognirepo" / "vector_db"
    return base / "chroma"
