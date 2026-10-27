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

Events go through a bounded, coalescing FIFO (``watch_queue.WatchQueue``, #117) drained by ONE consumer thread
in batches of at most ``indexing.batch_max`` files: ``indexing.queue_max`` caps the queue (a full queue never blocks
the event thread — it marks an overflow and a catch-up scan reconciles the tree once the queue drains), and
``indexing.max_latency_ms`` makes a constant stream of edits still flush. Queue state is written to
``<store>/index/watch_queue.json`` for the control API and the metrics endpoint.

NOTE: Do NOT start from `cognirepo index-repo`. The watcher is a daemon
thread and belongs to the `cognirepo serve` or `cognirepo watch` lifecycle.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
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

from core.config.atomic import atomic_json_dump
from core.config.paths import get_cognirepo_dir_for_repo
from intelligence.indexer.language_registry import is_supported
from intelligence.indexer.watch_queue import (
    DEFAULT_BATCH_MAX, DEFAULT_MAX_LATENCY_MS, DEFAULT_MAXSIZE, STATUS_FILE as _STATUS_FILE, WatchQueue,
)

if TYPE_CHECKING:
    from data.graph.behaviour_tracker import BehaviourTracker
    from data.graph.knowledge_graph import KnowledgeGraph
    from intelligence.indexer.ast_indexer import ASTIndexer

_DEFAULT_DEBOUNCE_MS = 500
_STATUS_MIN_INTERVAL_SECS = 1.0
_MAX_CATCHUP_PASSES = 10

# Dead + dangling ast_metadata.json/faiss_meta records to accumulate before a
# debounced flush pays for compact_faiss()'s full index rebuild. compact_faiss()
# itself no-ops cheaply when nothing is dead, but a full compaction reconstructs
# every live vector — too costly to run after every single keystroke-triggered
# save. See COGNIREPO-D-B follow-up.
_FAISS_COMPACT_DEAD_THRESHOLD = 25

log = logging.getLogger(__name__)


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
        cfg = self._load_indexing_cfg()
        self.debounce_ms = debounce_ms if debounce_ms is not None else self._cfg_int(cfg, "debounce_ms", _DEFAULT_DEBOUNCE_MS)
        self.batch_max = max(1, self._cfg_int(cfg, "batch_max", DEFAULT_BATCH_MAX))
        self.max_latency_ms = max(1, self._cfg_int(cfg, "max_latency_ms", DEFAULT_MAX_LATENCY_MS))

        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        # abs_path -> "reindex" | "remove": bounded, coalescing, FIFO; drained by one consumer thread (#117)
        self._wq = WatchQueue(self._cfg_int(cfg, "queue_max", DEFAULT_MAXSIZE))
        self._consumer: threading.Thread | None = None
        self._overflow_logged = False
        self._last_event = 0.0
        self._status_at = 0.0
        # Serializes the *body* of flush(). self._lock only guards the consumer thread / condition and is
        # never held across the expensive index+save section, so
        # two Timer threads could previously run that section concurrently and
        # mutate shared indexer.index_data / graph.G unsynchronized.
        # See COGNIREPO-D15 and the note in flush().
        self._flush_lock = threading.RLock()

    def _load_indexing_cfg(self) -> dict:
        """The ``indexing`` section of this repo's config.json ({} if absent or unreadable)."""
        try:
            cfg_path = os.path.join(get_cognirepo_dir_for_repo(self.repo_root), "config.json")
            if os.path.exists(cfg_path):
                with open(cfg_path, encoding="utf-8") as f:
                    section = json.load(f).get("indexing", {})
                return section if isinstance(section, dict) else {}
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return {}

    @staticmethod
    def _cfg_int(cfg: dict, key: str, default: int) -> int:
        try:
            return int(cfg.get(key, default))
        except (TypeError, ValueError):
            return default

    def _load_debounce_ms(self) -> int:
        """Read indexing.debounce_ms from this repo's config.json (default 500)."""
        return self._cfg_int(self._load_indexing_cfg(), "debounce_ms", _DEFAULT_DEBOUNCE_MS)

    @property
    def _pending(self) -> dict[str, str]:
        """Snapshot of the queued paths (path -> action). Assigning replaces the queue's contents."""
        return self._wq.snapshot()

    @_pending.setter
    def _pending(self, items: dict[str, str]) -> None:
        self._wq.replace(items)

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
        outcome = self._wq.put(action, abs_path)      # coalesces by path; never blocks the event thread
        if outcome == "overflow" and not self._overflow_logged:      # once per episode, not once per event
            self._overflow_logged = True
            log.warning("watcher queue full (%d paths): further new paths are not queued; a catch-up scan will "
                        "reconcile them once it drains", self._wq.maxsize)
        with self._cv:
            self._last_event = time.monotonic()
            if self._consumer is None or not self._consumer.is_alive():
                self._consumer = threading.Thread(target=self._consume, name="cognirepo-watch-consumer", daemon=True)
                self._consumer.start()
            self._cv.notify_all()

    def _consume(self) -> None:
        """The single consumer: wait for a quiet ``debounce_ms`` (or ``max_latency_ms`` of continuous churn), then
        drain. Exits as soon as the queue is empty — nothing idles between bursts, no thread per event."""
        debounce, latency = self.debounce_ms / 1000.0, self.max_latency_ms / 1000.0
        while True:
            with self._cv:
                while True:
                    if len(self._wq) == 0 and not self._wq.overflowed:
                        self._consumer = None
                        return
                    quiet = time.monotonic() - self._last_event
                    age = self._wq.oldest_age()
                    if quiet >= debounce or age >= latency:
                        break
                    self._cv.wait(timeout=max(0.01, min(debounce - quiet, latency - age) if age else debounce - quiet))
            try:
                self.flush()
            except Exception as exc:  # pylint: disable=broad-except
                print(f"[watcher] flush failed: {exc}", file=sys.stderr)

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
        """flush() body — callers must hold self._flush_lock. Drains the queue in batches of at most
        ``batch_max`` paths; if the queue overflowed meanwhile, reconciles with a catch-up scan and drains again."""
        passes = 0
        while True:
            while True:
                batch = self._wq.take_batch(self.batch_max)
                if not batch:
                    break
                started = time.monotonic()
                self._process_batch(dict(batch))
                self._wq.record_batch(len(batch), (time.monotonic() - started) * 1000)
                self._publish_status()
            if not self._wq.take_overflow():
                break
            self._overflow_logged = False
            passes += 1
            if passes > _MAX_CATCHUP_PASSES:
                log.warning("watcher queue kept overflowing; stopping reconciliation after %d passes", passes - 1)
                break
            if catch_up(self) == 0:
                log.warning("watcher queue overflowed and the catch-up scan found nothing to do (not a git "
                            "repo?); some changes may be missed until the next index-repo")
                break
        self._publish_status(force=True)

    def _publish_status(self, force: bool = False) -> None:
        """Write the queue's state to ``<store>/index/watch_queue.json`` (best effort, throttled)."""
        now = time.monotonic()
        if not force and now - self._status_at < _STATUS_MIN_INTERVAL_SECS:
            return
        self._status_at = now
        try:
            from datetime import datetime, timezone  # pylint: disable=import-outside-toplevel
            doc = {**self._wq.describe(), "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "pid": os.getpid(), "batch_max": self.batch_max, "debounce_ms": self.debounce_ms}
            atomic_json_dump(os.path.join(get_cognirepo_dir_for_repo(self.repo_root), "index", _STATUS_FILE),
                             doc, indent=None, fsync=False)
        except Exception:  # pylint: disable=broad-except
            pass

    def _follow_backend(self) -> None:
        """If ``storage.graph_backend`` changed since this watcher started (console toggle / ``graph migrate``),
        switch to a graph on the new backend before touching anything, so it never saves into the store that was
        just migrated away from. The indexer and behaviour tracker hold the same graph, so they follow."""
        try:
            from data.graph.backend import is_current  # pylint: disable=import-outside-toplevel
            if is_current(self.graph):
                return
            from data.graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
            fresh = KnowledgeGraph()
        except Exception:  # pylint: disable=broad-except
            return
        self.graph = fresh
        for holder in (self.indexer, self.behaviour):
            if getattr(holder, "graph", None) is not None:
                holder.graph = fresh
        log.info("graph backend changed; the watcher now uses %s", type(fresh).__name__)

    def _process_batch(self, pending: dict[str, str]) -> None:
        """Index, remove and persist one batch (the old flush body). Callers hold self._flush_lock."""
        self._follow_backend()
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
                print(f"[watcher] error processing {action} for {abs_path}: {exc}", file=sys.stderr)

        try:
            from intelligence.indexer import tombstones  # pylint: disable=import-outside-toplevel
            tombstones.clear(removed_rel_paths)     # removed here: nothing left to purge later
            # Collect deletions a hook tombstoned earlier whose grace window has passed (#169).
            touched_symbol_names |= self.indexer.purge_tombstones(root=self.repo_root)
        except Exception as exc:  # pylint: disable=broad-except
            print(f"[watcher] tombstone purge failed: {exc}", file=sys.stderr)

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
        self._maybe_compact_faiss()

        save_error: str | None = None
        try:
            self.indexer.save()
        except Exception as exc:  # pylint: disable=broad-except
            save_error = f"indexer.save failed: {exc}"
            print(f"[watcher] {save_error}", file=sys.stderr)

        try:
            self._save_graph()
        except Exception as exc:  # pylint: disable=broad-except
            save_error = f"{save_error + '; ' if save_error else ''}graph.save failed: {exc}"
            print(f"[watcher] graph.save failed: {exc}", file=sys.stderr)

        if save_error is None:
            self.indexer.finish_tombstones()      # purge persisted: the tombstones can go (#169)
        self._write_last_watcher_reindex(reindexed_rel_paths, removed_rel_paths, error=save_error)

        if any_reindexed:
            try:
                self.behaviour.save()
            except Exception as exc:  # pylint: disable=broad-except
                print(f"[watcher] behaviour.save failed: {exc}", file=sys.stderr)

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
            print(f"[watcher] removed {rel_path} from index", file=sys.stderr)

    def _save_graph(self) -> None:
        """self.graph.save(), recovering once from a circuit-breaker trip.

        COGNIREPO-98/105: the long-lived `serve` process keeps the embedding
        model warm across edits (evicting it after every debounced save would
        force a reload on the next keystroke-triggered reindex — unlike
        `cognirepo index-repo`'s one-shot _direct_index(), there IS a "next
        embed soon" here, so we don't evict proactively). But that means the
        model (~2 GB, see COGNIREPO-107) stays resident for the whole session
        alongside the growing graph, and a save here had no recovery at all
        if that combination ever crossed the circuit breaker's limit — it
        just logged and moved on, never freeing anything or retrying. This is
        the same failure class #107 found and fixed in _direct_index(), just
        reached through the watcher instead of a manual reindex. Reactive
        fix: only evict + retry once, on an actual trip.

        COGNIREPO-122: the watcher only ever applies per-file edits, so it must not
        publish a graph that is not a superset of what is on disk. If the graph it
        loaded is missing/quarantined/a fragment, skip the graph save (warn once) until a
        full `index-repo` provides a complete base.
        """
        ok, reason = self.graph.incremental_base_status(
            len(getattr(self.indexer, "index_data", {}).get("files", {}))
        )
        self._graph_skipped = None if ok else reason     # surfaced in last_watcher_reindex.json (#211)
        if not ok:
            if not getattr(self, "_warned_incomplete_base", False):
                self._warned_incomplete_base = True
                print(
                    f"[watcher] not saving the graph: {reason}. "
                    "Run `cognirepo index-repo .` once to build a complete base graph.",
                    file=sys.stderr,
                )
            return
        try:
            self.graph.save()
        except Exception as exc:  # pylint: disable=broad-except
            exc_name = type(exc).__name__
            if "CircuitOpen" not in exc_name and "CircuitBreaker" not in exc_name:
                raise
            from data.memory.embeddings import evict_model  # pylint: disable=import-outside-toplevel
            from data.memory.circuit_breaker import get_breaker  # pylint: disable=import-outside-toplevel
            evict_model()
            time.sleep(get_breaker().cooldown + 1)
            self.graph.save()  # let a second failure propagate to the caller

    def _maybe_compact_faiss(self) -> None:
        """Reclaim dead/dangling ast_metadata.json rows once enough have piled up.

        compact_faiss() previously only ran at the end of a full `index-repo`
        pass — the watcher's debounced reindexes only ever appended, so
        ast_metadata.json grew without bound across a long-lived watch
        session, even though the dead records were already unreachable via
        FAISS. Gated on a threshold (not every flush) since compact_faiss()
        reconstructs every live vector to rebuild the index — cheap to skip,
        not cheap to run on every keystroke-triggered save. See COGNIREPO-D-B
        follow-up.
        """
        try:
            stats = self.indexer.faiss_meta_stats()
            if stats["dead"] + stats["dangling"] >= _FAISS_COMPACT_DEAD_THRESHOLD:
                self.indexer.compact_faiss()
        except Exception as exc:  # pylint: disable=broad-except
            print(f"[watcher] compact_faiss failed: {exc}", file=sys.stderr)

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
                # Why the graph was NOT saved this batch (watcher refuses a base that is not a
                # complete graph, COGNIREPO-122); None when it was saved. Lets the console say
                # "run a full index-repo once" instead of the graph silently never updating (#211).
                "graph_skipped": getattr(self, "_graph_skipped", None),
            }
            path = os.path.join(get_cognirepo_dir_for_repo(self.repo_root), "index", "last_watcher_reindex.json")
            # status trail: atomic replace so readers never see a torn file, but no fsync —
            # it runs after every batch, and on a slow disk two fsyncs here delayed the flush
            atomic_json_dump(path, record, indent=2, fsync=False)
        except Exception as exc:  # pylint: disable=broad-except
            print(f"[watcher] failed to write last_watcher_reindex.json: {exc}", file=sys.stderr)
        if reindexed or removed or error:    # live event for the console (#207); best-effort, never raises
            from core import events  # pylint: disable=import-outside-toplevel
            events.emit("watcher.reindex", store_dir=str(get_cognirepo_dir_for_repo(self.repo_root)),
                        session_id=self.session_id, reindexed=reindexed, removed=removed, error=error)

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
        # node and any surviving symbols. index_file() itself already removes this
        # file's old FAISS ids (all of them, unconditionally) before re-embedding,
        # so a renamed-away symbol's vector is not left live/searchable — only the
        # ast_metadata.json record lingers as dead until compact_faiss() reclaims
        # it (see _maybe_compact_faiss()).
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
        old_names = self.indexer.remove_file(rel_path)   # shared with index-repo --files (#169)
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
            self._maybe_compact_faiss()
            self.indexer.save()
            self._save_graph()

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

            print(f"[watcher] removed {rel_path} from index", file=sys.stderr)
        except Exception as exc:  # pylint: disable=broad-except
            print(f"[watcher] error removing {abs_path}: {exc}", file=sys.stderr)

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
            self._maybe_compact_faiss()
            self.indexer.save()
            self._save_graph()
            self.behaviour.save()

            try:
                from intelligence.retrieval.hybrid import invalidate_hybrid_cache  # pylint: disable=import-outside-toplevel
                invalidate_hybrid_cache()
            except Exception:  # pylint: disable=broad-except
                pass

            print(f"[watcher] re-indexed {rel_path}", file=sys.stderr)
        except Exception as exc:  # pylint: disable=broad-except
            print(f"[watcher] error re-indexing {abs_path}: {exc}", file=sys.stderr)


def _parse_ts(value: str) -> float | None:
    """ISO-8601 ``indexed_at`` -> epoch seconds, or None if it is missing or unparseable."""
    from datetime import datetime  # pylint: disable=import-outside-toplevel
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return None


def find_stale_paths(repo_root: str, indexed_files: dict) -> tuple[list[str], list[str]]:
    """Compare the working tree with the AST index; returns ``(changed, removed)`` as absolute paths.

    Used on watcher start to cover downtime: nothing was observing while the watcher was down, so
    edits made then are in neither the index nor any event queue. *changed* are supported files
    that are new to the index or modified after their record's ``indexed_at``; *removed* are
    indexed files that are no longer on disk. Candidates come from ``git ls-files`` (tracked plus
    untracked-not-ignored), so ignore rules match ``index-repo`` / ``--changed-only``. Not a git
    repo (or git missing) -> ``([], [])`` rather than guessing; the live events still work.
    Cheap on purpose: stat() only. A touched-but-identical file is queued, and ``index_file``'s
    sha256 check then skips it.
    """
    import subprocess  # pylint: disable=import-outside-toplevel
    try:
        out = subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=repo_root, stderr=subprocess.DEVNULL,
        ).decode("utf-8", "surrogateescape")
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return [], []
    # `--cached` still lists a tracked file that was deleted from the working tree, so existence
    # is decided by stat(), not by git: a vanished file must fall through to `removed` below.
    mtimes: dict[str, float] = {}
    for rel in out.split("\0"):
        if rel and is_supported(Path(rel)):
            try:
                mtimes[rel] = os.stat(os.path.join(repo_root, rel)).st_mtime
            except OSError:
                pass

    changed: list[str] = []
    for rel, mtime in mtimes.items():
        abs_path = os.path.join(repo_root, rel)
        rec = indexed_files.get(rel)
        indexed_at = _parse_ts(rec.get("indexed_at", "")) if rec else None
        if rec is None or indexed_at is None or mtime > indexed_at:
            changed.append(abs_path)

    removed = [
        os.path.join(repo_root, rel) for rel in indexed_files
        if rel not in mtimes and is_supported(Path(rel))
        and not os.path.exists(os.path.join(repo_root, rel))
    ]
    return changed, removed


def catch_up(handler: RepoFileHandler) -> int:
    """Queue whatever changed while no watcher was running; returns how many paths were queued.

    Goes through the handler's normal debounced queue, so the batch is indexed, saved and
    tombstoned by exactly the code that handles live events.
    """
    try:
        changed, removed = find_stale_paths(handler.repo_root, handler.indexer.index_data.get("files", {}))
    except Exception as exc:  # pylint: disable=broad-except
        log.warning("watcher catch-up scan failed (%s); live events still work", exc)
        return 0
    for path in changed:
        handler._queue("reindex", path)  # pylint: disable=protected-access
    for path in removed:
        handler._queue("remove", path)  # pylint: disable=protected-access
    if changed or removed:
        log.info("watcher catch-up: %d changed, %d removed since the last index", len(changed), len(removed))
    return len(changed) + len(removed)


def create_watcher(
    repo_root: str,
    indexer: "ASTIndexer",
    graph: "KnowledgeGraph",
    behaviour: "BehaviourTracker",
    session_id: str,
    catch_up_on_start: bool = False,
) -> Observer:
    """
    Create, schedule, and start a watchdog Observer.
    Caller must call observer.stop() / observer.join() on shutdown — do that
    via stop_watching() below, which also flushes any pending debounced events.

    ``catch_up_on_start`` first queues files changed while nothing was watching (see ``catch_up``);
    the observer is already running, so an edit made during the scan is queued too.
    """
    handler = RepoFileHandler(repo_root, indexer, graph, behaviour, session_id)
    observer = Observer()
    observer.schedule(handler, repo_root, recursive=True)
    observer._cognirepo_handler = handler  # pylint: disable=protected-access
    observer.start()
    if catch_up_on_start:
        catch_up(handler)
    return observer
