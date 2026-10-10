# pylint: disable=duplicate-code
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Local vector database module using FAISS for storing and searching semantic embeddings.
"""

import os
import json
from datetime import datetime, timezone
# pylint: disable=import-error
import faiss
import numpy as np

from core.config.atomic import atomic_write
from core.config.generation import GenerationStore, link_or_copy
from core.config.safe_read import (
    StoreUnreadableError, looks_encrypted, quarantine_if_stably_corrupt, read_retry,
)
from core.config.paths import get_path
from core.config.lock import store_lock
from core.vector_db.adapter import VectorStorageAdapter


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()

def _index_file() -> str:
    return get_path("vector_db/semantic.index")

def _meta_file() -> str:
    return get_path("memory/semantic_metadata.json")


def _semantic_store() -> GenerationStore:
    """Generation store holding semantic.index + semantic_metadata.json (COGNIREPO-140)."""
    return GenerationStore(get_path("vector_db/semantic.gen"))


def _read_paths() -> tuple[str, str]:
    """(semantic.index, semantic_metadata.json) of ONE generation — never one of each era."""
    got = _semantic_store().resolve({
        "semantic.index": _index_file(),
        "semantic_metadata.json": _meta_file(),
    })
    return got["semantic.index"], got["semantic_metadata.json"]


def publish_semantic(index, meta_bytes: bytes, *, keep_index: bool = False) -> None:
    """Publish index + metadata as one generation. Caller holds ``store_lock()``.

    ``index`` is the in-memory FAISS index to write. With ``keep_index`` an existing index file is
    hard-linked into the new generation instead (no copy) — for metadata-only changes such as
    behaviour scores or soft-deletes; ``index`` is the fallback when there is none yet.
    ``meta_bytes`` is the final (already encrypted) content.
    """
    keep_from = _read_paths()[0] if keep_index else None
    if keep_from is not None and not os.path.exists(keep_from):
        keep_from = None

    def _index(path: str) -> None:
        if keep_from is not None:
            link_or_copy(keep_from, path)
        else:
            faiss.write_index(index, path)

    def _meta(path: str) -> None:
        atomic_write(path, meta_bytes, fsync=False)   # publish() fsyncs the whole group

    _semantic_store().publish(
        {"semantic.index": _index, "semantic_metadata.json": _meta},
        mirror={"semantic.index": _index_file(), "semantic_metadata.json": _meta_file()},
    )


class LocalVectorDB(VectorStorageAdapter):
    """
    Local vector database using FAISS for storing and searching semantic embeddings.
    """

    def __init__(self, dim=384, *, breaker_factory=None, cleanup_queue_factory=None):
        """
        Initializes the LocalVectorDB with the specified dimensionality.

        breaker_factory / cleanup_queue_factory — optional zero-arg callables
        supplied by the caller (e.g. get_vector_adapter()) that return a
        circuit breaker / CleanupQueue instance. Keeps this core-layer module
        free of upward `core → data` imports (COGNIREPO-D06) — callers in
        data/intelligence/interface wire in data.memory.circuit_breaker.get_breaker
        and data.memory.cleanup_queue.CleanupQueue.
        """
        import logging  # pylint: disable=import-outside-toplevel
        self.dim = dim
        self._breaker_factory = breaker_factory
        self._cleanup_queue_factory = cleanup_queue_factory
        # COGNIREPO-135: loading is side-effect free. An unreadable file is NOT renamed or
        # overwritten here (this constructor runs on every store_memory); it is remembered in
        # _load_error and a writer decides in _ensure_writable() — see core/config/safe_read.py.
        self._load_error: dict[str, StoreUnreadableError] = {}
        # Sample the on-disk stamp BEFORE reading (COGNIREPO-136). Sampled after, a save that
        # lands between our read and the stamp makes "synced" equal the NEWER state, so save()
        # would see no change and overwrite it with this stale snapshot — silently dropping
        # every vector the other process added.
        _stamp_before_read = self._disk_stamp()
        _mtime_before_read = self._disk_mtime()
        # One generation for both files (COGNIREPO-140): resolved once, so the index and its
        # metadata can never come from different saves.
        index_path, meta_path = _read_paths()
        if os.path.exists(index_path):
            try:
                self.index = read_retry(
                    index_path, lambda: faiss.read_index(index_path), retry_on=(Exception,),
                )
            except StoreUnreadableError as exc:
                logging.getLogger(__name__).warning(
                    "semantic.index could not be loaded (%s). Starting with an empty in-memory "
                    "index; the file is left untouched (this may be a platform mismatch or a "
                    "concurrent writer). Re-run `cognirepo index-repo .` to rebuild.",
                    exc.reason,
                )
                self._load_error["index"] = exc
                self.index = faiss.IndexFlatL2(dim)
        else:
            self.index = faiss.IndexFlatL2(dim)

        if os.path.exists(meta_path):
            try:
                self.metadata = self._load_meta(meta_path)
            except StoreUnreadableError as exc:
                logging.getLogger(__name__).warning("%s", exc)
                self._load_error["meta"] = exc
                self.metadata = []
        else:
            # Initialize eagerly. Atomic replace alone does NOT prevent the first-write race: a
            # process that saw "absent" could replace a file another process wrote in the
            # meantime with "[]", dropping its metadata (COGNIREPO-136). Re-check under the lock.
            os.makedirs(os.path.dirname(meta_path), exist_ok=True)
            with store_lock():
                if os.path.exists(meta_path):
                    self.metadata = self._load_meta(meta_path)
                else:
                    atomic_write(meta_path, b"[]")
                    self.metadata = []

        self._loaded_disk_mtime = _mtime_before_read
        # Vectors added but not yet saved, and the on-disk state this instance last synced
        # with. save() uses them to merge into newer disk state instead of overwriting another
        # process's vectors (see _sync_locked).
        self._pending: list[tuple] = []
        self._synced_stamp = _stamp_before_read

    # ── cross-process freshness ────────────────────────────────────────────────

    @staticmethod
    def _disk_mtime() -> float:
        """Newest mtime of the on-disk index + metadata pair (0.0 if absent)."""
        m = 0.0
        for p in (_index_file(), _meta_file()):
            try:
                m = max(m, os.path.getmtime(p))
            except OSError:
                pass
        return m

    @staticmethod
    def _disk_stamp() -> tuple:
        """(mtime_ns, size) of the index and metadata files — exact, unlike a float mtime."""
        out = []
        for p in (_index_file(), _meta_file()):
            try:
                st = os.stat(p)
                out.append((st.st_mtime_ns, st.st_size))
            except OSError:
                out.append(None)
        return tuple(out)

    def _sync_locked(self) -> None:
        """Merge into newer disk state. Caller holds store_lock().

        If another process saved since this instance last synced, our in-memory index/metadata
        are stale: saving them would silently drop its vectors (lost update). Reload from disk
        and re-apply only OUR unsaved adds on top, so rows are appended after the other
        process's. An unreadable disk state raises StoreUnreadableError — nothing is
        overwritten (#135).
        """
        if self._disk_stamp() == getattr(self, "_synced_stamp", None):
            return
        pending = list(getattr(self, "_pending", ()))
        index_path, meta_path = _read_paths()
        index = (read_retry(index_path, lambda: faiss.read_index(index_path),
                            retry_on=(Exception,))
                 if os.path.exists(index_path) else faiss.IndexFlatL2(self.dim))
        metadata = self._load_meta(meta_path) if os.path.exists(meta_path) else []
        for vec, entry in pending:
            index.add(vec)
            metadata.append(entry)
        self.index, self.metadata = index, metadata
        self._load_error = {}          # both files just read fine
        self._synced_stamp = self._disk_stamp()
        self._loaded_disk_mtime = self._disk_mtime()

    def _maybe_reload(self) -> None:
        """Reload index + metadata if another process wrote them since load.

        A long-lived MCP server otherwise serves a point-in-time snapshot:
        memories stored via the CLI or a second agent session are invisible
        until the server restarts. Mirrors the mtime pattern used by the
        episodic BM25 cache in retrieval/hybrid.py.
        """
        if getattr(self, "_pending", None):
            return  # unsaved adds would be dropped by a reload; save() merges them instead
        disk = self._disk_mtime()
        if disk <= self._loaded_disk_mtime:
            return
        stamp = self._disk_stamp()  # before reading, same reason as in __init__
        try:
            index_path, meta_path = _read_paths()
            if os.path.exists(index_path):
                self.index = faiss.read_index(index_path)
            if os.path.exists(meta_path):
                self.metadata = self._load_meta(meta_path)
            self._loaded_disk_mtime = disk
            self._synced_stamp = stamp
        except Exception:  # pylint: disable=broad-except
            # Keep serving the in-memory snapshot on any reload failure.
            pass

    # ── metadata persistence (with optional encryption) ───────────────────────

    def _read_meta_once(self, path: "str | None" = None) -> list:
        path = path or _read_paths()[1]
        with open(path, "rb") as f:
            raw = f.read()
        from core.security import get_storage_config  # pylint: disable=import-outside-toplevel
        encrypt, project_id = get_storage_config()
        if encrypt:
            from core.security.encryption import get_or_create_key, decrypt_bytes  # pylint: disable=import-outside-toplevel
            try:
                raw = decrypt_bytes(raw, get_or_create_key(project_id))
            except Exception:  # pylint: disable=broad-except
                # The file may have been written unencrypted by a process
                # that resolved the wrong config context — try plaintext
                # below before discarding (it gets encrypted on next save).
                # Genuinely corrupt/wrong-key content still fails the JSON
                # parse below and is backed up there.
                import logging  # pylint: disable=import-outside-toplevel
                logging.getLogger(__name__).warning(
                    "semantic_metadata.json could not be decrypted — attempting "
                    "plaintext load (file may predate the encryption setting)."
                )
        try:
            return json.loads(raw)
        except ValueError:
            if looks_encrypted(raw):
                # intact ciphertext we cannot decrypt: locked, never "corrupt"
                raise StoreUnreadableError(path, "encrypted and cannot be decrypted",
                                           locked=True)
            raise

    def _load_meta(self, path: "str | None" = None) -> list:
        """Read the metadata. Side-effect free: never renames or rewrites the file; raises
        StoreUnreadableError if it stays unreadable after a few retries (#135)."""
        path = path or _read_paths()[1]
        return read_retry(path, lambda: self._read_meta_once(path))

    def _ensure_writable(self) -> None:
        """Writer-side gate: refuse to persist over a store that failed to load.

        Saving the empty in-memory fallback would destroy a store that was merely unreadable
        (concurrent writer, missing key). Only if the file stays unreadable AND unchanged is
        it moved aside (bytes kept in ``<file>.corrupt-<ts>``) so a fresh one can be written.
        """
        if not getattr(self, "_load_error", None):
            return
        index_path, meta_path = _read_paths()
        probes = {
            "index": (index_path, lambda: faiss.read_index(index_path)),
            "meta": (meta_path, lambda: self._read_meta_once(meta_path)),
        }
        for key, exc in list(self._load_error.items()):
            if exc.locked:
                raise exc
            path, read = probes[key]

            def _readable(read=read) -> bool:
                try:
                    read()
                    return True
                except Exception:  # pylint: disable=broad-except
                    return False
            if _readable():
                raise StoreUnreadableError(
                    path, "store failed to load but is readable now (transient) — retry")
            if quarantine_if_stably_corrupt(path, _readable) is None:
                raise exc
            del self._load_error[key]

    def _save_meta(self, *, write_index: bool = False) -> None:
        """Publish the metadata (and, with ``write_index``, the in-memory FAISS index) as one
        generation. Metadata-only calls link the existing index file rather than rewriting it."""
        with store_lock():  # re-entrant: also called from inside save() / the row mutators
            self._ensure_writable()
            from core.security import get_storage_config  # pylint: disable=import-outside-toplevel
            encrypt, project_id = get_storage_config()
            content = json.dumps(self.metadata, indent=2).encode()
            if encrypt:
                from core.security.encryption import get_or_create_key, encrypt_bytes  # pylint: disable=import-outside-toplevel
                content = encrypt_bytes(content, get_or_create_key(project_id))
            publish_semantic(self.index, content, keep_index=not write_index)
            self._synced_stamp = self._disk_stamp()

    def save(self):
        """
        Saves the FAISS index and metadata to disk.
        Acquires a cross-process file lock so concurrent MCP server writes
        (e.g. Claude + Gemini both calling store_memory at the same time)
        do not corrupt the FAISS binary or metadata JSON.
        """
        breaker = self._breaker_factory() if self._breaker_factory is not None else None
        if breaker is not None:
            breaker.check()
        with store_lock():
            self._sync_locked()        # merge into any newer disk state first (#136)
            self._ensure_writable()
            self._save_meta(write_index=True)
            self._pending = []
        self._loaded_disk_mtime = self._disk_mtime()
        if breaker is not None:
            breaker.record_success()

    def add(self, vector, text, importance, source: str = "memory", behaviour_score: float = 0.0):
        """
        Adds a new vector and its associated metadata to the database.
        source — "memory" for episodic/semantic memories, "symbol" for code symbols.
        """
        vector = np.array([vector]).astype("float32")

        entry = {
            "text": text,
            "importance": importance,
            "source": source,
            "behaviour_score": behaviour_score,
        }
        self.index.add(vector)
        self.metadata.append(entry)
        self._pending.append((vector, entry))

        self.save()

    def add_batch(
        self,
        entries: list[tuple],
        source: str = "memory",
    ) -> int:
        """
        Add multiple vectors in one shot and save once at the end.

        Each entry is a tuple of (vector, text, importance) or
        (vector, text, importance, source) — the per-entry source overrides
        the default *source* argument when present.

        Returns the number of vectors successfully added.
        """
        if not entries:
            return 0
        for item in entries:
            vec, text, importance = item[0], item[1], item[2]
            entry_source = item[3] if len(item) > 3 else source
            vec = np.array([vec]).astype("float32")
            entry = {
                "text": text,
                "importance": importance,
                "source": entry_source,
                "behaviour_score": 0.0,
            }
            self.index.add(vec)
            self.metadata.append(entry)
            self._pending.append((vec, entry))
        self.save()
        return len(entries)

    def update_behaviour_score(self, row_id: int, new_score: float) -> bool:
        """Update behaviour_score for an existing entry by row index."""
        with store_lock():  # reload-modify-write: don't flush a stale snapshot (#136)
            self._sync_locked()
            if row_id < 0 or row_id >= len(self.metadata):
                return False
            self.metadata[row_id]["behaviour_score"] = float(new_score)
            self._save_meta()
            return True

    def deprecate_row(self, faiss_row: int) -> bool:
        """
        Soft-delete a vector by row index.
        The FAISS index is not rebuilt; the metadata entry is flagged so search
        results skip it.  Returns True if the row was found and updated.
        """
        with store_lock():
            self._sync_locked()
            if faiss_row < 0 or faiss_row >= len(self.metadata):
                return False
            self.metadata[faiss_row]["deprecated"] = True
            self._save_meta()
            return True

    def suppress_row(self, faiss_row: int, reason: str = "auto_superseded", similarity: float = 1.0) -> bool:
        """
        Auto-suppress a vector row — distinct from user-initiated deprecate_row().

        Marks the entry as suppressed=True so it is excluded from all searches,
        then enqueues it in CleanupQueue for deferred hard-deletion by the cron
        cleanup job.  The FAISS index is not rebuilt immediately.

        Returns True if the row was found and updated.
        """
        with store_lock():
            self._sync_locked()
            if faiss_row < 0 or faiss_row >= len(self.metadata):
                return False
            entry = self.metadata[faiss_row]
            if entry.get("suppressed") or entry.get("deprecated"):
                return False  # already suppressed/deprecated
            entry["suppressed"] = True
            entry["suppress_reason"] = reason
            entry["suppressed_at"] = _now_iso()
            self._save_meta()
        # Enqueue for priority-queue cleanup
        if self._cleanup_queue_factory is not None:
            try:
                self._cleanup_queue_factory().push(
                    entry_id=faiss_row,
                    store="semantic",
                    importance=float(entry.get("importance", 0.5)),
                    suppressed_at=entry["suppressed_at"],
                    similarity_score=float(similarity),
                )
            except Exception:  # pylint: disable=broad-except
                pass  # queue is best-effort
        return True

    def search(self, vector, top_k=5, source: str | None = None):
        """Searches for the top_k most similar vectors to the given query vector.
        source — optional filter: "memory" | "symbol". None means no filter.
        Deprecated entries are never returned.
        """
        self._maybe_reload()
        k = top_k
        vector = np.array([vector]).astype("float32")

        # fetch more candidates when filtering so we still return up to k
        fetch_k = min(k * 3 if source else k, self.index.ntotal) if self.index.ntotal > 0 else 0
        if fetch_k == 0:
            return []

        _, indices = self.index.search(vector, fetch_k)

        results = []
        for i in indices[0]:
            if i < len(self.metadata):
                record = self.metadata[i]
                if record.get("deprecated", False) or record.get("suppressed", False):
                    continue
                # entries without a "source" field are legacy memories
                if source and record.get("source", "memory") != source:
                    continue
                results.append(record)
                if len(results) == k:
                    break

        return results

    def search_with_scores(self, vector, top_k=5, source: str | None = None):
        """
        Like search() but each result also includes 'l2_distance' and 'faiss_row'.
        Used by HybridRetriever to compute vector_score = max(0, 1 - dist/2).
        source — optional filter: "memory" | "symbol". None means no filter.
        Deprecated entries are never returned.
        """
        self._maybe_reload()
        k = top_k
        vector = np.array([vector]).astype("float32")

        fetch_k = min(k * 3 if source else k, self.index.ntotal) if self.index.ntotal > 0 else 0
        if fetch_k == 0:
            return []

        distances, indices = self.index.search(vector, fetch_k)
        results = []
        for dist, i in zip(distances[0], indices[0]):
            if 0 <= i < len(self.metadata):
                record = self.metadata[i]
                if record.get("deprecated", False) or record.get("suppressed", False):
                    continue
                if source and record.get("source", "memory") != source:
                    continue
                entry = dict(record)
                entry["l2_distance"] = float(dist)
                entry["faiss_row"] = int(i)
                l2_score = max(0.0, 1.0 - float(dist) / 2.0)
                b_score = float(record.get("behaviour_score", 0.0))
                entry["combined_score"] = round(l2_score * 0.8 + b_score * 0.2, 4)
                results.append(entry)
                if len(results) == k:
                    break
        return results

    def remove(self, ids: list[int]) -> None:
        """Soft-remove via deprecate_row — FAISS does not support in-place deletion."""
        import logging  # pylint: disable=import-outside-toplevel
        _log = logging.getLogger(__name__)
        for row_id in ids:
            if not self.deprecate_row(row_id):
                _log.warning("LocalVectorDB.remove(): row %d out of range", row_id)

    def count(self) -> int:
        """Return total number of vectors in the FAISS index."""
        return self.index.ntotal

    def persist(self) -> None:
        """Flush index + metadata to disk."""
        self.save()
