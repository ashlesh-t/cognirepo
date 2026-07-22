# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
File watcher — uses watchdog to detect changes to any indexed file type
(.py, .ts, .tsx, .js, .go, .rs, .java, .cpp, …) and trigger incremental
re-indexing + graph updates.

Extension coverage is driven by language_registry.is_supported() so new
grammars are automatically watched as soon as they are installed.

Events are debounced and batched (config.json → "indexing": {"debounce_ms": 500}):
a burst of events for the same path within the window collapses to one
reindex/remove; a flush persists all of a batch's mutations with a single
indexer.save() + graph.save() instead of one pair per event. debounce_ms: 0
processes every event synchronously and individually (pre-debounce behavior).

NOTE: Do NOT start from `cognirepo index-repo`. The watcher is a daemon
thread and belongs to the `cognirepo serve` or `cognirepo watch` lifecycle.
"""
from __future__ import annotations

import json
import os
import threading
from typing import TYPE_CHECKING

from pathlib import Path

from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from core.config.paths import get_cognirepo_dir_for_repo
from intelligence.indexer.language_registry import is_supported

if TYPE_CHECKING:
    from data.graph.behaviour_tracker import BehaviourTracker
    from data.graph.knowledge_graph import KnowledgeGraph
    from intelligence.indexer.ast_indexer import ASTIndexer

_DEFAULT_DEBOUNCE_MS = 500


class RepoFileHandler(FileSystemEventHandler):
    """Watchdog handler that re-indexes any changed file whose extension is supported."""

    def __init__(
        self,
        repo_root: str,
        indexer: "ASTIndexer",
        graph: "KnowledgeGraph",
        behaviour: "BehaviourTracker",
        session_id: str,
        debounce_ms: int | None = None,
    ) -> None:
        super().__init__()
        self.repo_root = os.path.abspath(repo_root)
        self.indexer = indexer
        self.graph = graph
        self.behaviour = behaviour
        self.session_id = session_id
        self.debounce_ms = debounce_ms if debounce_ms is not None else self._load_debounce_ms()

        self._lock = threading.Lock()
        self._pending: dict[str, str] = {}  # abs_path -> "reindex" | "remove"
        self._timer: threading.Timer | None = None
        # Serializes the *body* of flush(). self._lock only guards _pending /
        # _timer and is released before the expensive index+save section, so
        # two Timer threads could previously run that section concurrently and
        # mutate shared indexer.index_data / graph.G unsynchronized.
        # See COGNIREPO-D15 and the note in flush().
        self._flush_lock = threading.RLock()

    def _load_debounce_ms(self) -> int:
        """Read indexing.debounce_ms from this repo's config.json (default 500)."""
        try:
            cfg_path = os.path.join(get_cognirepo_dir_for_repo(self.repo_root), "config.json")
            if os.path.exists(cfg_path):
                with open(cfg_path, encoding="utf-8") as f:
                    return int(json.load(f).get("indexing", {}).get("debounce_ms", _DEFAULT_DEBOUNCE_MS))
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return _DEFAULT_DEBOUNCE_MS

    # ── watchdog callbacks ────────────────────────────────────────────────────

    def on_modified(self, event: FileModifiedEvent) -> None:
        """Queue re-indexing when a supported file is modified."""
        if not event.is_directory and is_supported(Path(str(event.src_path))):
            self._queue("reindex", str(event.src_path))

    def on_created(self, event: FileCreatedEvent) -> None:
        """Queue re-indexing when a new supported file is created."""
        if not event.is_directory and is_supported(Path(str(event.src_path))):
            self._queue("reindex", str(event.src_path))

    def on_deleted(self, event: FileDeletedEvent) -> None:
        """Queue removal from the index when a supported file is deleted."""
        if not event.is_directory and is_supported(Path(str(event.src_path))):
            self._queue("remove", str(event.src_path))

    def on_moved(self, event: FileMovedEvent) -> None:
        """Queue removal of the old path + re-indexing of the new path on rename/move."""
        if event.is_directory:
            return
        src_path, dest_path = str(event.src_path), str(event.dest_path)
        if is_supported(Path(src_path)):
            self._queue("remove", src_path)
        if is_supported(Path(dest_path)):
            self._queue("reindex", dest_path)

    # ── debounce / batching ───────────────────────────────────────────────────

    def _queue(self, action: str, abs_path: str) -> None:
        if self.debounce_ms <= 0:
            # Disabled: process this single event immediately (pre-debounce behavior).
            # Still takes _flush_lock so a shutdown flush() can never overlap
            # with a synchronous save on the emitter thread (COGNIREPO-D15).
            with self._flush_lock:
                if action == "reindex":
                    self._reindex(abs_path)
                else:
                    self._remove(abs_path)
            return
        with self._lock:
            self._pending[abs_path] = action  # last action for a path wins; dedupes bursts
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce_ms / 1000.0, self.flush)
            self._timer.daemon = True
            self._timer.start()

    def flush(self) -> None:
        """
        Process all pending queued events as one batch: one indexer.save() +
        graph.save() + invalidate_hybrid_cache() for the whole batch, not per
        event. Called by the debounce timer, and by stop_watching() on
        shutdown so no queued events are lost.

        Serialized by self._flush_lock. threading.Timer.cancel() in _queue()
        is a no-op once the timer has already fired, so under a burst that
        outlasts the debounce window (5 saves over ~1 s at debounce_ms=500,
        with each editor save emitting several modify events) a second timer
        is scheduled while the first flush is still inside the seconds-long
        index+save section. Both threads then hit ASTIndexer.save() at once.
        See COGNIREPO-D15.
        """
        with self._flush_lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        """flush() body — callers must hold self._flush_lock."""
        with self._lock:
            pending = self._pending
            self._pending = {}
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        if not pending:
            return

        any_reindexed = False
        reindexed_rel_paths: list[str] = []
        removed_rel_paths: list[str] = []
        touched_symbol_names: set[str] = set()
        for abs_path, action in pending.items():
            try:
                if action == "reindex":
                    reindexed, names = self._reindex_mutate(abs_path)
                    if reindexed:
                        any_reindexed = True
                        reindexed_rel_paths.append(os.path.relpath(abs_path, self.repo_root))
                    touched_symbol_names |= names
                else:
                    rel_path, names = self._remove_mutate(abs_path)
                    if rel_path is not None:
                        removed_rel_paths.append(rel_path)
                    touched_symbol_names |= names
            except Exception as exc:  # pylint: disable=broad-except
                print(f"[watcher] error processing {action} for {abs_path}: {exc}")

        self.indexer._build_reverse_index()  # pylint: disable=protected-access
        # Scoped stub resolution: reconcile only the symbols this batch touched
        # (added or removed) instead of a full-graph sweep — keeps orphaned
        # symbol::* stubs from surviving deletion and total_symbols in sync
        # with the live index, without index_repo()'s O(all stubs) cost on
        # every debounced save. See COGNIREPO-D10.
        if touched_symbol_names:
            self.indexer._resolve_call_stubs(names=touched_symbol_names)  # pylint: disable=protected-access
        self.indexer.index_data["total_symbols"] = sum(
            len(f.get("symbols", [])) for f in self.indexer.index_data["files"].values()
        )
        # Persist + notify. Each step is independently guarded: previously
        # indexer.save() sat outside any handler, so a raise from it skipped
        # graph.save(), the D12 audit trail, episodic mark_stale(), AND
        # invalidate_hybrid_cache() — leaving the graph, the index and the
        # retrieval cache mutually inconsistent with no record that a batch
        # was ever attempted. That is precisely the cross-store divergence
        # E2E-100-1 exists to detect. See COGNIREPO-D15.
        save_error: str | None = None
        try:
            self.indexer.save()
        except Exception as exc:  # pylint: disable=broad-except
            save_error = f"indexer.save failed: {exc}"
            print(f"[watcher] {save_error}")

        try:
            self.graph.save()
        except Exception as exc:  # pylint: disable=broad-except
            save_error = f"{save_error + '; ' if save_error else ''}graph.save failed: {exc}"
            print(f"[watcher] graph.save failed: {exc}")

        self._write_last_watcher_reindex(reindexed_rel_paths, removed_rel_paths, error=save_error)

        if any_reindexed:
            try:
                self.behaviour.save()
            except Exception as exc:  # pylint: disable=broad-except
                print(f"[watcher] behaviour.save failed: {exc}")

        for rel_path in removed_rel_paths:
            try:
                from data.memory.episodic_memory import mark_stale  # pylint: disable=import-outside-toplevel
                mark_stale(rel_path)
            except Exception as _exc:  # pylint: disable=broad-except
                import logging as _logging  # pylint: disable=import-outside-toplevel
                _logging.getLogger(__name__).warning("episodic mark_stale failed for %s: %s", rel_path, _exc)

        # Must run even when a save failed: the in-memory stores were already
        # mutated, so a surviving TTL cache entry would serve pre-edit results.
        if any_reindexed or removed_rel_paths:
            try:
                from intelligence.retrieval.hybrid import invalidate_hybrid_cache  # pylint: disable=import-outside-toplevel
                invalidate_hybrid_cache()
            except Exception:  # pylint: disable=broad-except
                pass

        for rel_path in removed_rel_paths:
            print(f"[watcher] removed {rel_path} from index")

    def _write_last_watcher_reindex(
        self, reindexed: list[str], removed: list[str], error: str | None = None,
    ) -> None:
        """
        Overwrite `.cognirepo/index/last_watcher_reindex.json` with this batch's
        activity — a durable, mode-independent trail of watcher-driven reindex
        events. Without this, `flush()`'s only "logging" was a bare `print()`,
        invisible unless `cognirepo watch` happened to be running in daemon
        mode (which redirects stdout to a log file). Last-write-wins by
        design — no unbounded growth. See COGNIREPO-D12.
        """
        try:
            from datetime import datetime, timezone  # pylint: disable=import-outside-toplevel

            record = {
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "session_id": self.session_id,
                "reindexed": reindexed,
                "removed": removed,
                # None on a clean batch; a message when a persist step failed,
                # so a partially-applied batch is visible to `doctor` and to
                # anyone reading the trail, instead of looking like a success.
                "error": error,
            }
            path = os.path.join(get_cognirepo_dir_for_repo(self.repo_root), "index", "last_watcher_reindex.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2)
        except Exception as exc:  # pylint: disable=broad-except
            print(f"[watcher] failed to write last_watcher_reindex.json: {exc}")

    # ── mutate-only helpers (no save/side-effects — used by flush()'s batch) ──

    def _reindex_mutate(self, abs_path: str) -> tuple[bool, set[str]]:
        """
        Re-index one file's graph nodes + AST entry, without saving.

        Returns (True on success, the union of symbol names defined in the
        file before and after re-indexing — i.e. everything added or removed
        by this mutation, for scoped call-stub resolution in flush()).
        """
        rel_path = os.path.relpath(abs_path, self.repo_root)
        old_names = {
            s["name"] for s in
            self.indexer.index_data.get("files", {}).get(rel_path, {}).get("symbols", [])
        }
        # remove_file_nodes (not remove_node_edges) so symbols deleted from the file
        # don't leave orphaned nodes behind — index_file() below re-adds the FILE
        # node and any surviving symbols.
        self.graph.remove_file_nodes(rel_path)
        file_record = self.indexer.index_file(rel_path, abs_path)
        new_names = {s["name"] for s in (file_record or {}).get("symbols", [])}
        self.behaviour.record_file_edit(rel_path, self.session_id)
        return True, old_names | new_names

    def _remove_mutate(self, abs_path: str) -> tuple[str | None, set[str]]:
        """
        Remove one file's FAISS vectors + graph nodes + index_data entry.

        Returns (rel_path or None on error, the symbol names that were
        defined in the file — for scoped call-stub resolution in flush()).
        """
        rel_path = os.path.relpath(abs_path, self.repo_root)
        existing = self.indexer.index_data.get("files", {}).get(rel_path, {})
        old_names = {s["name"] for s in existing.get("symbols", [])}
        old_ids = [
            s["faiss_id"]
            for s in existing.get("symbols", [])
            if s.get("faiss_id", -1) >= 0
        ]
        if old_ids and self.indexer.faiss_index is not None:
            try:
                import numpy as np  # pylint: disable=import-outside-toplevel
                self.indexer.faiss_index.remove_ids(np.array(old_ids, dtype=np.int64))
            except Exception as _exc:  # pylint: disable=broad-except
                import logging as _logging  # pylint: disable=import-outside-toplevel
                _logging.getLogger(__name__).warning("FAISS remove_ids failed for %s: %s", abs_path, _exc)

        self.graph.remove_file_nodes(rel_path)
        self.indexer.index_data["files"].pop(rel_path, None)
        return rel_path, old_names

    # ── synchronous single-event helpers (debounce_ms=0, or direct calls) ────

    def _remove(self, abs_path: str) -> None:
        """
        Remove a deleted file from ALL four stores atomically:

        1. FAISS (AST index): remove symbol vector IDs via remove_ids().
        2. Knowledge graph: remove all symbol nodes + FILE node (+ edges).
        3. Reverse index / index_data: pop file entry, rebuild, save.
        4. Episodic memory: mark matching entries stale (history preserved).
        5. Invalidate the hybrid-retrieve TTL cache.
        """
        try:
            rel_path, names = self._remove_mutate(abs_path)
            if rel_path is None:
                return

            self.indexer._build_reverse_index()  # pylint: disable=protected-access
            if names:
                self.indexer._resolve_call_stubs(names=names)  # pylint: disable=protected-access
            self.indexer.index_data["total_symbols"] = sum(
                len(f.get("symbols", [])) for f in self.indexer.index_data["files"].values()
            )
            self.indexer.save()
            self.graph.save()

            try:
                from data.memory.episodic_memory import mark_stale  # pylint: disable=import-outside-toplevel
                mark_stale(rel_path)
            except Exception as _exc:  # pylint: disable=broad-except
                import logging as _logging  # pylint: disable=import-outside-toplevel
                _logging.getLogger(__name__).warning("episodic mark_stale failed for %s: %s", abs_path, _exc)

            try:
                from intelligence.retrieval.hybrid import invalidate_hybrid_cache  # pylint: disable=import-outside-toplevel
                invalidate_hybrid_cache()
            except Exception as _exc:  # pylint: disable=broad-except
                import logging as _logging  # pylint: disable=import-outside-toplevel
                _logging.getLogger(__name__).warning("cache invalidation failed: %s", _exc)

            print(f"[watcher] removed {rel_path} from index")
        except Exception as exc:  # pylint: disable=broad-except
            print(f"[watcher] error removing {abs_path}: {exc}")

    def _reindex(self, abs_path: str) -> None:
        """
        Re-index one file:
        1. Remove stale graph nodes/edges for this file.
        2. Re-index via ASTIndexer (sha256 check skips if unchanged).
        3. Rebuild reverse index.
        4. Save indexer + graph.
        5. Notify behaviour tracker (triggers co-occurrence + auto-useful heuristic).
        """
        try:
            _, names = self._reindex_mutate(abs_path)

            rel_path = os.path.relpath(abs_path, self.repo_root)
            self.indexer._build_reverse_index()  # pylint: disable=protected-access
            if names:
                self.indexer._resolve_call_stubs(names=names)  # pylint: disable=protected-access
            self.indexer.index_data["total_symbols"] = sum(
                len(f.get("symbols", [])) for f in self.indexer.index_data["files"].values()
            )
            self.indexer.save()
            self.graph.save()
            self.behaviour.save()

            try:
                from intelligence.retrieval.hybrid import invalidate_hybrid_cache  # pylint: disable=import-outside-toplevel
                invalidate_hybrid_cache()
            except Exception:  # pylint: disable=broad-except
                pass

            print(f"[watcher] re-indexed {rel_path}")
        except Exception as exc:  # pylint: disable=broad-except
            print(f"[watcher] error re-indexing {abs_path}: {exc}")


def create_watcher(
    repo_root: str,
    indexer: "ASTIndexer",
    graph: "KnowledgeGraph",
    behaviour: "BehaviourTracker",
    session_id: str,
) -> Observer:
    """
    Create, schedule, and start a watchdog Observer.
    Caller must call observer.stop() / observer.join() on shutdown — do that
    via stop_watching() below, which also flushes any pending debounced events.
    """
    handler = RepoFileHandler(repo_root, indexer, graph, behaviour, session_id)
    observer = Observer()
    observer.schedule(handler, repo_root, recursive=True)
    observer._cognirepo_handler = handler  # pylint: disable=protected-access
    observer.start()
    return observer
