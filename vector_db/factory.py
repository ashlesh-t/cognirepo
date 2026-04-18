# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""
vector_db/factory.py
Reads storage.vector_backend from .cognirepo/config.json and returns
the appropriate VectorStorageAdapter implementation.
Defaults to "faiss" if config unreadable or key missing.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from vector_db.adapter import VectorStorageAdapter

_log = logging.getLogger(__name__)


def get_vector_adapter(dim: int = 384) -> VectorStorageAdapter:
    """Return FAISS or ChromaDB adapter based on config.json storage.vector_backend."""
    backend = _read_backend()
    if backend == "chroma":
        try:
            from vector_db.chroma_adapter import ChromaDBAdapter  # pylint: disable=import-outside-toplevel
            path = _get_vector_db_path()
            _log.debug("vector backend: chroma at %s", path)
            return ChromaDBAdapter(path=str(path))
        except ImportError:
            _log.warning(
                "chromadb not installed — falling back to faiss. "
                "Run: pip install chromadb"
            )
    _log.debug("vector backend: faiss")
    from vector_db.local_vector_db import LocalVectorDB  # pylint: disable=import-outside-toplevel
    return LocalVectorDB(dim=dim)


def _read_backend() -> str:
    try:
        config_path = _find_config()
        if config_path and config_path.exists():
            data = json.loads(config_path.read_text(encoding="utf-8"))
            return data.get("storage", {}).get("vector_backend", "faiss")
    except Exception:  # pylint: disable=broad-except
        pass
    return "faiss"


def _find_config() -> Path | None:
    """Walk up from cwd to find .cognirepo/config.json."""
    for parent in [Path.cwd(), *Path.cwd().parents]:
        candidate = parent / ".cognirepo" / "config.json"
        if candidate.exists():
            return candidate
    return None


def _get_vector_db_path() -> Path:
    config = _find_config()
    if config:
        return config.parent / "vector_db"
    return Path.home() / ".cognirepo" / "vector_db"
