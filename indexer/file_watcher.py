"""
File watcher — uses watchdog to detect .py file changes and trigger
incremental re-indexing + graph updates.

NOTE: Do NOT start from `cognirepo index-repo`. The watcher is a daemon
thread and belongs to the `cognirepo serve` or `cognirepo watch` lifecycle.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from watchdog.events import FileCreatedEvent, FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

if TYPE_CHECKING:
    from graph.behaviour_tracker import BehaviourTracker
    from graph.knowledge_graph import KnowledgeGraph
    from indexer.ast_indexer import ASTIndexer


class RepoFileHandler(FileSystemEventHandler):
    """Watchdog handler that re-indexes changed Python files."""

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
        if not event.is_directory and str(event.src_path).endswith(".py"):
            self._reindex(str(event.src_path))

    def on_created(self, event: FileCreatedEvent) -> None:
        if not event.is_directory and str(event.src_path).endswith(".py"):
            self._reindex(str(event.src_path))

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
            self.indexer._build_reverse_index()  # rebuild top-level dict
            self.indexer.save()
            self.graph.save()

            # behaviour tracking
            self.behaviour.record_file_edit(rel_path, self.session_id)
            self.behaviour.save()

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
