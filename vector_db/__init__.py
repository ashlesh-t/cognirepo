# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
vector_db package — vector storage adapters.

Use get_storage_adapter() to obtain the backend configured in config.json.
The default backend is FAISS (LocalVectorDB).
"""
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vector_db.adapter import VectorStorageAdapter


def get_storage_adapter() -> "VectorStorageAdapter":
    """Return the VectorStorageAdapter configured in .cognirepo/config.json.

    Supported backends (config.json: {"vector_backend": "<name>"}):
      "faiss"  — default, backed by LocalVectorDB / IndexFlatL2
      "chroma" — ChromaDB persistent client (requires: pip install chromadb)

    Falls back to FAISS if config is absent or backend is unrecognised.
    """
    from config.paths import get_path  # pylint: disable=import-outside-toplevel

    backend = "faiss"
    config_path = get_path("config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, encoding="utf-8") as fh:
                cfg = json.load(fh)
            backend = cfg.get("vector_backend", "faiss")
        except (json.JSONDecodeError, OSError):
            pass

    if backend == "chroma":
        from vector_db.chroma_adapter import ChromaDBAdapter  # pylint: disable=import-outside-toplevel
        return ChromaDBAdapter()

    from vector_db.local_vector_db import LocalVectorDB  # pylint: disable=import-outside-toplevel
    return LocalVectorDB()
