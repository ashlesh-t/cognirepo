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

Run modes
---------
  --dry-run      Print what would be pruned without changing anything
  --aggressive   Lower threshold to 0.05 (prunes more aggressively)
  --archive      Move pruned entries to .cognirepo/archive/ instead of deleting

Schedule via cron (add to crontab -e):
  0 3 * * * cd /your/project && venv/bin/python -m cron.prune_memory

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

# ── paths ─────────────────────────────────────────────────────────────────────
# NOTE: resolved lazily via get_path() to respect --project-dir / COGNIREPO_DIR

def _semantic_meta() -> str:
    from config.paths import get_path  # pylint: disable=import-outside-toplevel
    return get_path("memory/semantic_metadata.json")

def _semantic_index() -> str:
    from config.paths import get_path  # pylint: disable=import-outside-toplevel
    return get_path("vector_db/semantic.index")

def _archive_dir() -> str:
    from config.paths import get_path  # pylint: disable=import-outside-toplevel
    return get_path("archive")

def _graph_pkl() -> str:
    from config.paths import get_path  # pylint: disable=import-outside-toplevel
    return get_path("graph/graph.pkl")

# Keep module-level names for backward compat (point at legacy hardcoded values only as fallback)
ARCHIVE_DIR = ".cognirepo/archive"
GRAPH_PKL = ".cognirepo/graph/graph.pkl"

DEFAULT_THRESHOLD = 0.15
AGGRESSIVE_THRESHOLD = 0.05


# ── circuit breaker guard ─────────────────────────────────────────────────────

def _check_memory_pressure() -> bool:
    """Return True if it is safe to proceed (circuit CLOSED)."""
    try:
        from memory.circuit_breaker import get_breaker  # pylint: disable=import-outside-toplevel
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
        from memory.embeddings import get_model  # pylint: disable=import-outside-toplevel

        model = get_model()
        texts = [e.get("text", "") for e in kept]
        vectors = np.array(list(model.embed(texts))).astype("float32")
        dim = vectors.shape[1]
        index = faiss.IndexFlatL2(dim)
        index.add(vectors)  # pylint: disable=no-value-for-parameter
        faiss.write_index(index, _semantic_index())
        # rewrite metadata with contiguous row IDs
        for i, entry in enumerate(kept):
            entry["faiss_row"] = i
        with open(_semantic_meta(), "w", encoding="utf-8") as f:
            json.dump(kept, f, indent=2)
        return len(kept)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[prune] FAISS rebuild failed: {exc}", file=sys.stderr)
        return -1


# ── graph pruning ─────────────────────────────────────────────────────────────

def _prune_graph(dry_run: bool) -> dict[str, int]:
    """Remove orphan nodes (no edges) and very cold concept nodes."""
    stats = {"orphans_removed": 0, "cold_nodes_removed": 0}
    if not os.path.exists(_graph_pkl()):
        return stats
    try:
        from graph.knowledge_graph import KnowledgeGraph, NodeType  # pylint: disable=import-outside-toplevel
        kg = KnowledgeGraph()
        orphans = [n for n in list(kg.G.nodes()) if kg.G.degree(n) == 0]
        stats["orphans_removed"] = len(orphans)
        if not dry_run:
            kg.G.remove_nodes_from(orphans)
        # Remove concept nodes with no edges (very cold)
        cold = [
            n for n in list(kg.G.nodes())
            if kg.G.nodes[n].get("node_type") == NodeType.CONCEPT
            and kg.G.degree(n) <= 1
        ]
        stats["cold_nodes_removed"] = len(cold)
        if not dry_run:
            kg.G.remove_nodes_from(cold)
            kg.save()
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[prune] Graph pruning failed: {exc}", file=sys.stderr)
    return stats


# ── archive helpers ───────────────────────────────────────────────────────────

def _archive_entries(entries: list[dict[str, Any]]) -> str:
    archive_dir = _archive_dir()
    os.makedirs(archive_dir, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(archive_dir, f"pruned_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
    return path


# ── main pruning logic ────────────────────────────────────────────────────────

def prune(
    threshold: float = DEFAULT_THRESHOLD,
    dry_run: bool = False,
    archive: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """
    Score and prune semantic memories.

    Returns a summary dict with keys:
      total, kept, pruned, archive_path, graph_stats, faiss_vectors
    """
    if not _check_memory_pressure():
        print("[prune] Memory pressure too high — skipping prune run", file=sys.stderr)
        return {"skipped": True, "reason": "circuit_breaker_open"}

    if not os.path.exists(_semantic_meta()):
        print("[prune] No semantic metadata found — nothing to prune")
        return {"total": 0, "kept": 0, "pruned": 0}

    with open(_semantic_meta(), encoding="utf-8") as f:
        entries: list[dict[str, Any]] = json.load(f)

    total = len(entries)
    scored = [(e, _final_score(e)) for e in entries]

    kept_pairs = [(e, s) for e, s in scored if s >= threshold]
    pruned_pairs = [(e, s) for e, s in scored if s < threshold]

    kept = [e for e, _ in kept_pairs]
    pruned = [e for e, _ in pruned_pairs]

    if verbose or dry_run:
        msg = (
            f"[prune] total={total}  kept={len(kept)}  "
            f"pruned={len(pruned)}  threshold={threshold}"
        )
        print(msg)
        for e, s in sorted(pruned_pairs, key=lambda x: x[1]):
            age = _days_old(e)
            print(f"  PRUNE score={s:.3f}  age={age:.1f}d  text={e.get('text','')[:60]}")

    archive_path = ""
    if pruned and not dry_run:
        if archive:
            archive_path = _archive_entries(pruned)
            print(f"[prune] archived {len(pruned)} entries → {archive_path}")
        faiss_count = _rebuild_faiss(kept, dry_run=False)
        if faiss_count < 0:
            print("[prune] FAISS rebuild failed — index may be corrupt", file=sys.stderr)
            return {"status": "error", "message": "FAISS rebuild failed",
                    "total": total, "kept": len(kept), "pruned": len(pruned)}
    else:
        faiss_count = len(kept)

    graph_stats = _prune_graph(dry_run=dry_run)

    summary = {
        "total": total,
        "kept": len(kept),
        "pruned": len(pruned),
        "archive_path": archive_path,
        "graph_stats": graph_stats,
        "faiss_vectors": faiss_count,
        "dry_run": dry_run,
    }
    if not dry_run:
        print(f"[prune] Done. {len(kept)}/{total} memories kept. "
              f"Graph: {graph_stats['orphans_removed']} orphans removed.")
    return summary


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
        from memory.cleanup_queue import CleanupQueue          # pylint: disable=import-outside-toplevel
        from vector_db.local_vector_db import LocalVectorDB    # pylint: disable=import-outside-toplevel
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
    with open(_semantic_meta(), "wb") as f:
        import json as _json  # pylint: disable=import-outside-toplevel,redefined-outer-name
        from security import get_storage_config  # pylint: disable=import-outside-toplevel
        encrypt, project_id = get_storage_config()
        content = _json.dumps(db.metadata, indent=2).encode()
        if encrypt:
            from security.encryption import get_or_create_key, encrypt_bytes  # pylint: disable=import-outside-toplevel
            content = encrypt_bytes(content, get_or_create_key(project_id))
        f.write(content)

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
    from dotenv import load_dotenv  # pylint: disable=import-outside-toplevel
    load_dotenv()
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
