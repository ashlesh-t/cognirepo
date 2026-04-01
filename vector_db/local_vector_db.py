# pylint: disable=duplicate-code
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Local vector database module using FAISS for storing and searching semantic embeddings.
"""

import os
import json
# pylint: disable=import-error
import faiss
import numpy as np

from config.paths import get_path

def _index_file() -> str:
    return get_path("vector_db/semantic.index")

def _meta_file() -> str:
    return get_path("memory/semantic_metadata.json")


class LocalVectorDB:
    """
    Local vector database using FAISS for storing and searching semantic embeddings.
    """

    def __init__(self, dim=384):
        """
        Initializes the LocalVectorDB with the specified dimensionality.
        """
        self.dim = dim
        if os.path.exists(_index_file()):
            self.index = faiss.read_index(_index_file())
        else:
            self.index = faiss.IndexFlatL2(dim)

        if os.path.exists(_meta_file()):
            self.metadata = self._load_meta()
        else:
            self.metadata = []

    # ── metadata persistence (with optional encryption) ───────────────────────

    def _load_meta(self) -> list:
        with open(_meta_file(), "rb") as f:
            raw = f.read()
        from security import get_storage_config  # pylint: disable=import-outside-toplevel
        encrypt, project_id = get_storage_config()
        if encrypt:
            from security.encryption import get_or_create_key, decrypt_bytes  # pylint: disable=import-outside-toplevel
            try:
                raw = decrypt_bytes(raw, get_or_create_key(project_id))
            except Exception:  # pylint: disable=broad-except
                # Key mismatch or corrupted file — start with a clean slate.
                # The stale file will be overwritten on the next save().
                import logging  # pylint: disable=import-outside-toplevel
                logging.getLogger(__name__).warning(
                    "semantic_metadata.json could not be decrypted (key mismatch or "
                    "corruption). Starting with empty metadata — existing entries will "
                    "be lost on next store_memory call."
                )
                return []
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            import logging  # pylint: disable=import-outside-toplevel
            logging.getLogger(__name__).warning(
                "semantic_metadata.json is not valid JSON. Starting with empty metadata."
            )
            return []

    def _save_meta(self) -> None:
        from security import get_storage_config  # pylint: disable=import-outside-toplevel
        encrypt, project_id = get_storage_config()
        content = json.dumps(self.metadata, indent=2).encode()
        if encrypt:
            from security.encryption import get_or_create_key, encrypt_bytes  # pylint: disable=import-outside-toplevel
            content = encrypt_bytes(content, get_or_create_key(project_id))
        os.makedirs(os.path.dirname(_meta_file()), exist_ok=True)
        with open(_meta_file(), "wb") as f:
            f.write(content)

    def save(self):
        """
        Saves the FAISS index and metadata to disk.
        """
        faiss.write_index(self.index, _index_file())
        self._save_meta()

    def add(self, vector, text, importance):
        """
        Adds a new vector and its associated metadata to the database.
        """
        vector = np.array([vector]).astype("float32")

        self.index.add(vector)

        self.metadata.append({
            "text": text,
            "importance": importance
        })

        self.save()

    def search(self, vector, k=5):
        """
        Searches for the k most similar vectors to the given query vector.
        """
        vector = np.array([vector]).astype("float32")

        _, indices = self.index.search(vector, k)

        results = []

        for i in indices[0]:
            if i < len(self.metadata):
                results.append(self.metadata[i])

        return results

    def search_with_scores(self, vector, k=5):
        """
        Like search() but each result also includes 'l2_distance' and 'faiss_row'.
        Used by HybridRetriever to compute vector_score = max(0, 1 - dist/2).
        """
        vector = np.array([vector]).astype("float32")
        distances, indices = self.index.search(vector, k)
        results = []
        for dist, i in zip(distances[0], indices[0]):
            if 0 <= i < len(self.metadata):
                record = dict(self.metadata[i])
                record["l2_distance"] = float(dist)
                record["faiss_row"] = int(i)
                results.append(record)
        return results
