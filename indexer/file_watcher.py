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

NOTE: Do NOT start from `cognirepo index-repo`. The watcher is a daemon
thread and belongs to the `cognirepo serve` or `cognirepo watch` lifecycle.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from pathlib import Path

from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from indexer.language_registry import is_supported

if TYPE_CHECKING:
    from graph.behaviour_tracker import BehaviourTracker
    from graph.knowledge_graph import KnowledgeGraph
    from indexer.ast_indexer import ASTIndexer


class RepoFileHandler(FileSystemEventHandler):
    """Watchdog handler that re-indexes any changed file whose extension is supported."""

    def __init__(
        self,
        repo_root: str,
        indexer: "ASTIndexer",
        graph: "KnowledgeGraph",
        behaviour: "BehaviourTracker",
        session_id: str,
    ) -> None:
        super().__init__()
        self.repo_root = os.path.abspath(repo_root)
        self.indexer = indexer
        self.graph = graph
        self.behaviour = behaviour
        self.session_id = session_id

    def on_modified(self, event: FileModifiedEvent) -> None:
        """Trigger re-indexing when a supported file is modified."""
        if not event.is_directory and is_supported(Path(str(event.src_path))):
            self._reindex(str(event.src_path))

    def on_created(self, event: FileCreatedEvent) -> None:
        """Trigger re-indexing when a new supported file is created."""
        if not event.is_directory and is_supported(Path(str(event.src_path))):
            self._reindex(str(event.src_path))

    def on_deleted(self, event: FileDeletedEvent) -> None:
        """Remove file from index when it is deleted from disk."""
        if not event.is_directory and is_supported(Path(str(event.src_path))):
            self._remove(str(event.src_path))

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
            rel_path = os.path.relpath(abs_path, self.repo_root)

            # 1. Remove FAISS symbol vectors for this file
            existing = self.indexer.index_data.get("files", {}).get(rel_path, {})
            old_ids = [
                s["faiss_id"]
                for s in existing.get("symbols", [])
                if s.get("faiss_id", -1) >= 0
            ]
            if old_ids and self.indexer.faiss_index is not None:
                try:
                    import numpy as np  # pylint: disable=import-outside-toplevel
                    self.indexer.faiss_index.remove_ids(
                        np.array(old_ids, dtype=np.int64)
                    )
                except Exception as _exc:  # pylint: disable=broad-except
                    import logging as _logging  # pylint: disable=import-outside-toplevel
                    _logging.getLogger(__name__).warning("FAISS remove_ids failed for %s: %s", abs_path, _exc)

            # 2. Remove graph nodes (symbols + FILE node) — edges removed automatically
            self.graph.remove_file_nodes(rel_path)

            # 3. Remove from index_data, rebuild reverse index, persist
            self.indexer.index_data["files"].pop(rel_path, None)
            self.indexer._build_reverse_index()  # pylint: disable=protected-access
            self.indexer.save()
            self.graph.save()

            # 4. Tag matching episodic entries as stale (not deleted)
            try:
                from memory.episodic_memory import mark_stale  # pylint: disable=import-outside-toplevel
                mark_stale(rel_path)
            except Exception as _exc:  # pylint: disable=broad-except
                import logging as _logging  # pylint: disable=import-outside-toplevel
                _logging.getLogger(__name__).warning("episodic mark_stale failed for %s: %s", abs_path, _exc)

            # 5. Invalidate retrieval cache so stale results are not served
            try:
                from retrieval.hybrid import invalidate_hybrid_cache  # pylint: disable=import-outside-toplevel
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
            rel_path = os.path.relpath(abs_path, self.repo_root)

            # remove stale graph nodes for this file
            stale_nodes = self.graph.nodes_for_file(rel_path)
            for node_id in stale_nodes:
                self.graph.remove_node_edges(node_id)

            # re-index the file
            self.indexer.index_file(rel_path, abs_path)
            self.indexer._build_reverse_index()  # pylint: disable=protected-access  # rebuild top-level dict
            self.indexer.save()
            self.graph.save()

            # behaviour tracking
            self.behaviour.record_file_edit(rel_path, self.session_id)
            self.behaviour.save()

            # invalidate retrieval cache so fresh symbols are served
            try:
                from retrieval.hybrid import invalidate_hybrid_cache  # pylint: disable=import-outside-toplevel
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
    Caller must call observer.stop() / observer.join() on shutdown.
    """
    handler = RepoFileHandler(repo_root, indexer, graph, behaviour, session_id)
    observer = Observer()
    observer.schedule(handler, repo_root, recursive=True)
    observer.start()
    return observer
