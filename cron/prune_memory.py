# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

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
SEMANTIC_META = ".cognirepo/memory/semantic_metadata.json"
SEMANTIC_INDEX = "vector_db/semantic.index"
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
        from memory.embeddings import get_model  # pylint: disable=import-outside-toplevel

        model = get_model()
        texts = [e.get("text", "") for e in kept]
        vectors = model.encode(texts, normalize_embeddings=True).astype("float32")
        dim = vectors.shape[1]
        index = faiss.IndexFlatL2(dim)
        index.add(vectors)  # pylint: disable=no-value-for-parameter
        faiss.write_index(index, SEMANTIC_INDEX)
        # rewrite metadata with contiguous row IDs
        for i, entry in enumerate(kept):
            entry["faiss_row"] = i
        with open(SEMANTIC_META, "w", encoding="utf-8") as f:
            json.dump(kept, f, indent=2)
        return len(kept)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[prune] FAISS rebuild failed: {exc}", file=sys.stderr)
        return -1


# ── graph pruning ─────────────────────────────────────────────────────────────

def _prune_graph(dry_run: bool) -> dict[str, int]:
    """Remove orphan nodes (no edges) and very cold concept nodes."""
    stats = {"orphans_removed": 0, "cold_nodes_removed": 0}
    if not os.path.exists(GRAPH_PKL):
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
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(ARCHIVE_DIR, f"pruned_{ts}.json")
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

    if not os.path.exists(SEMANTIC_META):
        print("[prune] No semantic metadata found — nothing to prune")
        return {"total": 0, "kept": 0, "pruned": 0}

    with open(SEMANTIC_META, encoding="utf-8") as f:
        entries: list[dict[str, Any]] = json.load(f)

    total = len(entries)
    scored = [(e, _final_score(e)) for e in entries]

    kept_pairs = [(e, s) for e, s in scored if s >= threshold]
    pruned_pairs = [(e, s) for e, s in scored if s < threshold]

    kept = [e for e, _ in kept_pairs]
    pruned = [e for e, _ in pruned_pairs]

    if verbose or dry_run:
        print(f"[prune] total={total}  kept={len(kept)}  pruned={len(pruned)}  threshold={threshold}")
        for e, s in sorted(pruned_pairs, key=lambda x: x[1]):
            age = _days_old(e)
            print(f"  PRUNE score={s:.3f}  age={age:.1f}d  text={e.get('text','')[:60]}")

    archive_path = ""
    if pruned and not dry_run:
        if archive:
            archive_path = _archive_entries(pruned)
            print(f"[prune] archived {len(pruned)} entries → {archive_path}")
        faiss_count = _rebuild_faiss(kept, dry_run=False)
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


# ── CLI entry ─────────────────────────────────────────────────────────────────

def main() -> None:
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
