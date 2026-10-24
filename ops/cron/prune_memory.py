# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Memory pruner — scores every memory by importance × recency_decay, archives
entries below threshold, rebuilds FAISS index, and prunes the knowledge graph.

Scoring
-------
  final_score = importance_score * e^(-0.1 * days_old)

  Gentle exponential decay: a memory at day-0 = full importance, day-7 = 0.50×,
  day-23 = 0.10×.  This keeps recently-accessed memories alive without a hard cutoff.

  NOTE: semantic-memory entries carry no timestamp today, so their age reads as 0 and the score is
  just ``importance`` (0.2 per keyword, plus length/100 up to 1) — a memory is pruned when that is
  below the threshold, however old it is.

Run modes
---------
  --dry-run      Print what would be pruned without changing anything
  --aggressive   Lower threshold to 0.05 (prunes more aggressively)
  --archive      Move pruned entries to .cognirepo/archive/ instead of deleting

Schedule via cron (add to crontab -e):
  0 3 * * * cd /your/project && venv/bin/python -m ops.cron.prune_memory

Or via the CLI:
  cognirepo prune --dry-run
  cognirepo prune --aggressive
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from typing import Any
from core.config.atomic import atomic_json_dump

# ── paths ─────────────────────────────────────────────────────────────────────
# NOTE: resolved lazily via get_path() to respect --project-dir / COGNIREPO_DIR

def _semantic_meta() -> str:
    from core.config.paths import get_path  # pylint: disable=import-outside-toplevel
    return get_path("memory/semantic_metadata.json")

def _semantic_index() -> str:
    from core.config.paths import get_path  # pylint: disable=import-outside-toplevel
    return get_path("vector_db/semantic.index")

def _archive_dir() -> str:
    from core.config.paths import get_path  # pylint: disable=import-outside-toplevel
    return get_path("archive")

def _graph_pkl() -> str:
    """The graph's file under the active backend (graph.pkl, or graph.sqlite when that backend is on)."""
    from data.graph.backend import graph_store_path  # pylint: disable=import-outside-toplevel
    return graph_store_path()

# Keep module-level names for backward compat (point at legacy hardcoded values only as fallback)
ARCHIVE_DIR = ".cognirepo/archive"
GRAPH_PKL = ".cognirepo/graph/graph.pkl"

DEFAULT_THRESHOLD = 0.15
AGGRESSIVE_THRESHOLD = 0.05


# ── circuit breaker guard ─────────────────────────────────────────────────────

def _check_memory_pressure() -> bool:
    """Return True if it is safe to proceed (circuit CLOSED)."""
    try:
        from data.memory.circuit_breaker import get_breaker  # pylint: disable=import-outside-toplevel
        get_breaker().check()
        return True
    except Exception:  # pylint: disable=broad-except
        return False


# ── recency decay ─────────────────────────────────────────────────────────────

def _days_old(entry: dict[str, Any]) -> float:
    """Return how many days old an entry is (0 if timestamp missing)."""
    ts = entry.get("timestamp") or entry.get("created_at") or entry.get("time")
    if not ts:
        return 0.0
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(tz=timezone.utc) - dt
        return max(0.0, delta.total_seconds() / 86400)
    except (ValueError, TypeError):
        return 0.0


def _recency_decay(days: float, k: float = 0.1) -> float:
    """e^(-k * days)  → 1.0 at day 0, ~0.5 at day 7, ~0.1 at day 23."""
    return math.exp(-k * days)


def _final_score(entry: dict[str, Any]) -> float:
    importance = float(entry.get("importance", 0.0))
    days = _days_old(entry)
    return importance * _recency_decay(days)


# ── FAISS rebuild ─────────────────────────────────────────────────────────────

def _rebuild_faiss(kept: list[dict[str, Any]], dry_run: bool) -> int:
    """
    Re-encode kept entries and rebuild semantic.index from scratch.
    Returns number of vectors in the new index.
    """
    if dry_run or not kept:
        return len(kept)
    try:
        import faiss  # pylint: disable=import-outside-toplevel
        import numpy as np  # pylint: disable=import-outside-toplevel
        from data.memory.embeddings import get_model  # pylint: disable=import-outside-toplevel

        model = get_model()
        texts = [e.get("text", "") for e in kept]
        vectors = np.array(list(model.embed(texts))).astype("float32")
        dim = vectors.shape[1]
        index = faiss.IndexFlatL2(dim)
        index.add(vectors)  # pylint: disable=no-value-for-parameter
        # rewrite metadata with contiguous row IDs
        for i, entry in enumerate(kept):
            entry["faiss_row"] = i
        # index + metadata go out as ONE generation, under the lock (COGNIREPO-140): written one
        # after the other, a reader between the two renames paired the new index with old rows.
        from core.config.lock import store_lock  # pylint: disable=import-outside-toplevel
        from core.vector_db.local_vector_db import publish_semantic  # pylint: disable=import-outside-toplevel
        from core.vector_db.local_vector_db import encode_semantic_metadata  # pylint: disable=import-outside-toplevel
        with store_lock():
            publish_semantic(index, encode_semantic_metadata(kept))   # encrypted when storage.encrypt is on
        return len(kept)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[prune] FAISS rebuild failed: {exc}", file=sys.stderr)
        return -1


# ── graph pruning ─────────────────────────────────────────────────────────────

def _prune_graph(dry_run: bool) -> dict[str, int]:
    """Remove orphan nodes (degree 0).

    There used to be a second step for "very cold concept nodes" that matched ``node_type == CONCEPT`` and
    ``degree <= 1``. The attribute is really called ``type``, so it never matched anything — and "fixing" the
    name would have deleted every ``symbol::<callee>`` call-graph stub with a single caller, which ``who_calls``
    needs. A concept node with no edges at all is an orphan and is covered above, so the step was removed.
    """
    stats = {"orphans_removed": 0, "cold_nodes_removed": 0}
    if not os.path.exists(_graph_pkl()):
        return stats
    try:
        from data.graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        kg = KnowledgeGraph()
        orphans = kg.isolated_node_ids()
        stats["orphans_removed"] = len(orphans)
        if not dry_run and orphans:
            for _nid in orphans:
                kg.remove_node_if_degree_at_most(_nid, 0)
            kg.save()
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[prune] Graph pruning failed: {exc}", file=sys.stderr)
    return stats


# ── archive helpers ───────────────────────────────────────────────────────────

def _archive_entries(entries: list[dict[str, Any]]) -> str:
    """Write the pruned entries to ``archive/pruned_<ts>.json`` — encrypted when ``storage.encrypt`` is on, since
    they hold the memory text the encryption exists to protect."""
    from core.security.store_crypto import encode_store  # pylint: disable=import-outside-toplevel
    archive_dir = _archive_dir()
    os.makedirs(archive_dir, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    path = os.path.join(archive_dir, f"pruned_{ts}.json")
    from core.config.atomic import atomic_write  # pylint: disable=import-outside-toplevel
    atomic_write(path, encode_store(json.dumps(entries, indent=2).encode("utf-8")), fsync=True)
    return path


# ── prune state (for the console: "dry-run first", last result, auto schedule) ─

STATE_FILE = "prune_state.json"
DRY_RUN_VALID_SECS = 1800     # a real run from the console needs a dry run no older than this


def _state_path() -> str:
    from core.config.paths import get_path  # pylint: disable=import-outside-toplevel
    return get_path(STATE_FILE)


def read_state() -> dict[str, Any]:
    try:
        with open(_state_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _record_state(result: dict[str, Any], dry_run: bool) -> None:
    """Remember the counts of the latest run (never the memory text). Best-effort."""
    try:
        state = read_state()
        entry = {"at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "status": result.get("status") or ("skipped" if result.get("skipped") else "ok"),
                 **{k: result[k] for k in ("total", "kept", "pruned") if k in result}}
        state["last_dry_run" if dry_run else "last_run"] = entry
        atomic_json_dump(_state_path(), state, indent=None, fsync=False)
    except Exception:  # pylint: disable=broad-except
        pass


def dry_run_is_fresh(now: float | None = None) -> bool:
    """True if a dry run completed within ``DRY_RUN_VALID_SECS``."""
    import time  # pylint: disable=import-outside-toplevel
    at = (read_state().get("last_dry_run") or {}).get("at")
    try:
        ts = datetime.strptime(str(at), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return False
    return 0 <= (time.time() if now is None else now) - ts <= DRY_RUN_VALID_SECS


# ── main pruning logic ────────────────────────────────────────────────────────

PREVIEW_MAX = 50


def _score_entries(entries: list[dict[str, Any]], threshold: float):
    scored = [(e, _final_score(e)) for e in entries]
    return [i for i, (_e, s) in enumerate(scored) if s >= threshold], \
           [i for i, (_e, s) in enumerate(scored) if s < threshold], scored


def _apply_locked(threshold: float, archive: bool) -> dict[str, Any]:
    """Prune the semantic store. Read, score, archive and republish all happen under ``store_lock()``.

    The old version read the metadata outside the lock, spent seconds re-embedding every kept entry, then
    published — so a memory stored in between was silently dropped. Vectors are now copied out of the
    existing FAISS index (row ``i`` is metadata ``i``) instead of re-embedded, so the work is short, needs no
    embedding model, and the lock is held for all of it.
    """
    import faiss  # pylint: disable=import-outside-toplevel
    import numpy as np  # pylint: disable=import-outside-toplevel
    from core.config.lock import store_lock  # pylint: disable=import-outside-toplevel
    from core.vector_db.local_vector_db import (  # pylint: disable=import-outside-toplevel
        _read_paths, encode_semantic_metadata, publish_semantic, read_semantic_metadata)

    with store_lock():
        entries = read_semantic_metadata()
        total = len(entries)
        keep_rows, drop_rows, _ = _score_entries(entries, threshold)
        out: dict[str, Any] = {"total": total, "kept": len(keep_rows), "pruned": len(drop_rows),
                               "archive_path": "", "faiss_vectors": len(keep_rows)}
        if not drop_rows:
            return out
        index = faiss.read_index(_read_paths()[0])
        if index.ntotal != total:
            return {**out, "kept": total, "pruned": 0, "status": "error",
                    "message": f"the FAISS index has {index.ntotal} vectors but the metadata {total} entries; "
                               "nothing was changed"}
        if archive:
            out["archive_path"] = _archive_entries([entries[i] for i in drop_rows])
        vectors = index.reconstruct_n(0, total)[keep_rows] if keep_rows else np.empty((0, index.d), "float32")
        rebuilt = faiss.IndexFlatL2(index.d)
        if len(keep_rows):
            rebuilt.add(np.ascontiguousarray(vectors, dtype="float32"))  # pylint: disable=no-value-for-parameter
        kept = [entries[i] for i in keep_rows]
        for row, entry in enumerate(kept):
            entry["faiss_row"] = row
        publish_semantic(rebuilt, encode_semantic_metadata(kept))
        return out


def prune(
    threshold: float = DEFAULT_THRESHOLD,
    dry_run: bool = False,
    archive: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """
    Score and prune semantic memories, then drop orphan graph nodes.

    Returns a summary dict with keys:
      total, kept, pruned, archive_path, graph_stats, faiss_vectors, dry_run
    (plus ``preview`` — the lowest-scoring candidates, text clipped — on a dry run). A store that changes under
    it, an unreadable one, or a FAISS/metadata mismatch is reported in ``status`` and left untouched.
    """
    import time  # pylint: disable=import-outside-toplevel
    started = time.monotonic()
    if not _check_memory_pressure():
        print("[prune] Memory pressure too high — skipping prune run", file=sys.stderr)
        return {"skipped": True, "reason": "circuit_breaker_open"}

    if not os.path.exists(_semantic_meta()):
        print("[prune] No semantic metadata found — nothing to prune")
        return {"total": 0, "kept": 0, "pruned": 0}

    if dry_run:
        from core.vector_db.local_vector_db import read_semantic_metadata  # pylint: disable=import-outside-toplevel
        entries = read_semantic_metadata(_semantic_meta())
        keep_rows, drop_rows, scored = _score_entries(entries, threshold)
        result: dict[str, Any] = {"total": len(entries), "kept": len(keep_rows), "pruned": len(drop_rows),
                                  "archive_path": "", "faiss_vectors": len(keep_rows)}
        worst = sorted(drop_rows, key=lambda i: scored[i][1])
        result["preview"] = [{"text": str(entries[i].get("text", ""))[:80], "score": round(scored[i][1], 3),
                              "age_days": round(_days_old(entries[i]), 1)} for i in worst[:PREVIEW_MAX]]
        result["preview_truncated"] = len(worst) > PREVIEW_MAX
    else:
        result = _apply_locked(threshold, archive)
        if result.get("status") == "error":
            print(f"[prune] {result.get('message')}", file=sys.stderr)
            _record_state(result, dry_run=False)
            return result
        if result.get("archive_path"):
            print(f"[prune] archived {result['pruned']} entries → {result['archive_path']}")

    if verbose or dry_run:
        print(f"[prune] total={result['total']}  kept={result['kept']}  "
              f"pruned={result['pruned']}  threshold={threshold}")
        for item in result.get("preview", []):
            print(f"  PRUNE score={item['score']:.3f}  age={item['age_days']:.1f}d  text={item['text'][:60]}")

    graph_stats = _prune_graph(dry_run=dry_run)
    result.update(graph_stats=graph_stats, dry_run=dry_run)
    if not dry_run:
        print(f"[prune] Done. {result['kept']}/{result['total']} memories kept. "
              f"Graph: {graph_stats['orphans_removed']} orphans removed.")
    _record_state(result, dry_run)
    try:
        from core import events  # pylint: disable=import-outside-toplevel
        events.emit("prune", dry_run=dry_run, total=result["total"], kept=result["kept"], pruned=result["pruned"],
                    orphans_removed=graph_stats["orphans_removed"], archived=bool(result["archive_path"]),
                    dur_ms=int((time.monotonic() - started) * 1000))
    except Exception:  # pylint: disable=broad-except
        pass
    return result


# ── suppression cleanup ───────────────────────────────────────────────────────

def cleanup_suppressed(
    batch_size: int = 50,
    rebuild_threshold: float = 0.20,
    dry_run: bool = False,
) -> dict:
    """
    Drain the CleanupQueue and hard-delete auto-suppressed entries.

    Algorithm:
    1. Pop `batch_size` highest-priority items from CleanupQueue.
    2. For each semantic-store item, promote suppressed→deprecated in metadata
       (so it stays excluded from search even if rebuild doesn't happen yet).
    3. If the fraction of dead rows (suppressed or deprecated) exceeds
       `rebuild_threshold`, rebuild the FAISS index from scratch using only
       the surviving rows.

    Returns a summary dict with counts and whether a rebuild was triggered.
    """
    if not _check_memory_pressure():
        return {"skipped": True, "reason": "circuit_open"}

    try:
        from data.memory.cleanup_queue import CleanupQueue          # pylint: disable=import-outside-toplevel
        from core.vector_db.local_vector_db import LocalVectorDB    # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        return {"error": str(exc)}

    queue = CleanupQueue()
    queue_len = len(queue)
    if queue_len == 0:
        return {"deleted": 0, "rebuilt": False, "queue_was_empty": True}

    batch = queue.pop_batch(batch_size)
    semantic_rows = [
        int(item["entry_id"])
        for item in batch
        if item.get("store") == "semantic"
    ]

    if not semantic_rows or dry_run:
        return {"deleted": len(batch), "rebuilt": False, "dry_run": dry_run}

    db = LocalVectorDB()
    for row in semantic_rows:
        if 0 <= row < len(db.metadata):
            # Promote to deprecated so _rebuild_faiss keeps filter consistent
            db.metadata[row]["deprecated"] = True

    # Persist promoted flags immediately (without a full rebuild)
    # Content (incl. encryption) is computed BEFORE the file is touched, and the swap is
    # atomic: a failure in encrypt_bytes() used to leave the metadata truncated (COGNIREPO-134).
    import json as _json  # pylint: disable=import-outside-toplevel,redefined-outer-name
    from core.security import get_storage_config  # pylint: disable=import-outside-toplevel
    encrypt, project_id = get_storage_config()
    content = _json.dumps(db.metadata, indent=2).encode()
    if encrypt:
        from core.security.encryption import get_or_create_key, encrypt_bytes  # pylint: disable=import-outside-toplevel
        content = encrypt_bytes(content, get_or_create_key(project_id))
    from core.config.lock import store_lock  # pylint: disable=import-outside-toplevel
    from core.vector_db.local_vector_db import publish_semantic  # pylint: disable=import-outside-toplevel
    with store_lock():
        publish_semantic(db.index, content, keep_index=True)

    # Check rebuild threshold
    total = len(db.metadata)
    dead = sum(
        1 for m in db.metadata
        if m.get("deprecated") or m.get("suppressed")
    )
    rebuilt = False
    if total > 0 and dead / total >= rebuild_threshold:
        kept = [
            m for m in db.metadata
            if not m.get("deprecated") and not m.get("suppressed")
        ]
        rebuild_result = _rebuild_faiss(kept, dry_run=False)
        rebuilt = rebuild_result >= 0

    return {
        "deleted": len(batch),
        "semantic_rows_cleaned": len(semantic_rows),
        "rebuilt": rebuilt,
        "dead_fraction": round(dead / total, 3) if total else 0.0,
        "queue_remaining": max(0, queue_len - len(batch)),
    }


# ── CLI entry ─────────────────────────────────────────────────────────────────

def main() -> None:
    """CLI entry point for pruning semantic memory."""
    from dotenv import load_dotenv, find_dotenv  # pylint: disable=import-outside-toplevel
    # usecwd=True: resolve .env from the project directory, not this source file
    load_dotenv(find_dotenv(usecwd=True))
    parser = argparse.ArgumentParser(description="Prune CogniRepo semantic memory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report only — do not modify any files")
    parser.add_argument("--aggressive", action="store_true",
                        help=f"Lower threshold to {AGGRESSIVE_THRESHOLD}")
    parser.add_argument("--archive", action="store_true",
                        help="Move pruned entries to .cognirepo/archive/ instead of dropping")
    parser.add_argument("--threshold", type=float, default=None,
                        help="Override pruning threshold (default 0.15)")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print the summary as one JSON line (last line of output)")
    args = parser.parse_args()

    threshold = args.threshold
    if threshold is None:
        threshold = AGGRESSIVE_THRESHOLD if args.aggressive else DEFAULT_THRESHOLD

    result = prune(
        threshold=threshold,
        dry_run=args.dry_run,
        archive=args.archive,
        verbose=args.verbose,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
