# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Hybrid retrieval — merges three signals into a single ranked result list.

  final_score = w_vector * vector_score
              + w_graph  * graph_score
              + w_behav  * behaviour_score

Score normalization:
  vector_score   = max(0, 1 - l2_distance / 2.0)       → [0, 1]
  graph_score    = 1 / (1 + hop_distance)               → [0, 1], 0 if disconnected
  behaviour_score = log(1+count) / log(1+max_count)     → [0, 1], log-normalized

Cold start: graph empty → graph_score=0, behaviour empty → behaviour_score=0.
Formula degrades gracefully to pure vector search.

Weights are read from .cognirepo/config.json → retrieval_weights.
Default: {"vector": 0.5, "graph": 0.3, "behaviour": 0.2}
"""
import json
import math
import os
import time

import numpy as np

from _bm25 import BM25 as _BM25, Document as _Document
from graph.behaviour_tracker import BehaviourTracker
from graph.graph_utils import extract_entities_from_text, make_node_id
from graph.knowledge_graph import KnowledgeGraph
from indexer.ast_indexer import ASTIndexer
from memory.embeddings import get_model
from memory.episodic_memory import get_history
from vector_db.local_vector_db import LocalVectorDB

from config.paths import get_path

def _config_file() -> str:
    return get_path("config.json")
DEFAULT_WEIGHTS = {"vector": 0.5, "graph": 0.3, "behaviour": 0.2}


def _load_weights() -> dict[str, float]:
    if os.path.exists(_config_file()):
        try:
            with open(_config_file(), encoding="utf-8") as f:
                cfg = json.load(f)
            w = cfg.get("retrieval_weights", DEFAULT_WEIGHTS)
            total = sum(w.values())
            if abs(total - 1.0) > 1e-6:
                raise ValueError(f"retrieval_weights must sum to 1.0, got {total:.4f}")
            return w
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULT_WEIGHTS


class HybridRetriever:  # pylint: disable=too-few-public-methods
    """
    Single entry point for all memory retrieval in CogniRepo.
    Instantiate once; call retrieve() repeatedly.
    """

    def __init__(self) -> None:
        self.weights = _load_weights()
        self.model = get_model()
        self.db = LocalVectorDB()
        self.graph = KnowledgeGraph()
        self.behaviour = BehaviourTracker(self.graph)
        self.indexer = ASTIndexer(graph=self.graph)
        self.indexer.load()

    # ── public API ────────────────────────────────────────────────────────────

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Return top_k results ranked by hybrid score.

        Each result dict contains:
          text, importance, source, final_score,
          vector_score, graph_score, behaviour_score
        """
        query_vector = self.model.encode(query).astype("float32")

        # 1. wider vector net before re-ranking
        vector_candidates = self._vector_retrieve(query_vector, top_k * 3)

        # 2. AST reverse-index expansion
        entities = extract_entities_from_text(query)
        ast_candidates = self._ast_retrieve(entities)

        # 3. merge + dedup
        all_candidates = self._merge_candidates(vector_candidates, ast_candidates)

        if not all_candidates:
            return []

        # 4. score
        all_counts = self.behaviour.get_all_scores()
        scored = self._score_candidates(all_candidates, entities, all_counts)

        # 5. sort + truncate
        scored.sort(key=lambda x: x["final_score"], reverse=True)
        return scored[:top_k]

    # ── private helpers ───────────────────────────────────────────────────────

    def _vector_retrieve(self, query_vector: np.ndarray, k: int) -> list[dict]:
        """Search semantic FAISS index; converts L2 distances to [0,1] scores."""
        if self.db.index.ntotal == 0:
            return []
        actual_k = min(k, self.db.index.ntotal)
        raw = self.db.search_with_scores(query_vector, actual_k)
        results = []
        for r in raw:
            dist = r.get("l2_distance", 2.0)
            results.append({
                "text": r.get("text", ""),
                "importance": r.get("importance", 0.5),
                "source": "semantic",
                "vector_score": max(0.0, 1.0 - dist / 2.0),
                "_id": r.get("text", ""),  # dedup key
            })
        return results

    def _ast_retrieve(self, entities: list[str]) -> list[dict]:
        """O(1) reverse-index lookups for each extracted entity."""
        results = []
        seen: set[str] = set()
        for entity in entities:
            for loc in self.indexer.lookup_symbol(entity):
                file_path = loc["file"]
                line = loc["line"]
                # find docstring from index
                file_data = self.indexer.index_data.get("files", {}).get(file_path, {})
                sym = next(
                    (s for s in file_data.get("symbols", []) if s["name"] == entity),
                    None,
                )
                doc = sym.get("docstring", "") if sym else ""
                sym_type = sym.get("type", "SYMBOL") if sym else "SYMBOL"
                text = f"{sym_type} {entity} in {file_path}:{line}" + (f" — {doc}" if doc else "")
                key = f"{file_path}::{entity}"
                if key not in seen:
                    seen.add(key)
                    results.append({
                        "text": text,
                        "importance": 0.5,
                        "source": "ast",
                        "vector_score": 0.0,
                        "_id": key,
                        "_symbol": make_node_id(sym_type, entity, file_path),
                    })
        return results

    def _merge_candidates(
        self,
        vector_candidates: list[dict],
        ast_candidates: list[dict],
    ) -> list[dict]:
        """Deduplicate by _id; AST candidates that match vector ones inherit vector_score."""
        merged: dict[str, dict] = {}
        for c in vector_candidates:
            merged[c["_id"]] = c
        for c in ast_candidates:
            if c["_id"] not in merged:
                merged[c["_id"]] = c
        return list(merged.values())

    def _score_candidates(
        self,
        candidates: list[dict],
        query_entities: list[str],
        all_counts: dict[str, float],
    ) -> list[dict]:
        max_count = max(all_counts.values(), default=0.0)
        scored = []
        for c in candidates:
            v_score = c.get("vector_score", 0.0)
            g_score = self._graph_score(c, query_entities)
            b_score = self._behaviour_score(c, all_counts, max_count)
            final = (
                self.weights["vector"] * v_score
                + self.weights["graph"] * g_score
                + self.weights["behaviour"] * b_score
            )
            result = dict(c)
            result.update({
                "final_score": round(final, 4),
                "vector_score": round(v_score, 4),
                "graph_score": round(g_score, 4),
                "behaviour_score": round(b_score, 4),
            })
            result.pop("_id", None)
            result.pop("_symbol", None)
            scored.append(result)
        return scored

    def _graph_score(self, candidate: dict, query_entities: list[str]) -> float:
        """1 / (1 + min_hop_distance) across all query entities → [0, 1].

        Uses the AST reverse index to resolve file-qualified node IDs
        (e.g. `tools/store_memory.py::store_memory`) so same-symbol candidates
        score 1.0 immediately, and one-hop neighbours score 0.5.
        Falls back to undirected path search when no directed path exists.
        """
        if not query_entities or self.graph.G.number_of_nodes() == 0:
            return 0.0

        # candidate node id: prefer explicit _symbol, fall back to text-derived
        cand_node = candidate.get("_symbol")
        if not cand_node:
            cand_node = f"concept::{candidate.get('text', '')[:40].lower()}"

        # Build undirected view once per call (cheap — same underlying graph)
        g_undirected = self.graph.G.to_undirected()

        min_hops = None
        for entity in query_entities:
            # Collect all candidate node IDs for this entity:
            # 1. Generic forms (concept/file/symbol prefixes)
            entity_node_ids = [
                entity,
                make_node_id("CONCEPT", entity),
                make_node_id("FILE", entity),
                f"symbol::{entity}",
            ]
            # 2. File-qualified forms from the AST reverse index — this is the
            #    key addition: file::entity may be the same node as cand_node,
            #    giving hop=0 (exact match) instead of the infinite distance
            #    between the orphan symbol:: stub and the real filepath:: node.
            for loc in self.indexer.lookup_symbol(entity):
                entity_node_ids.append(f"{loc['file']}::{entity}")

            for node_id in entity_node_ids:
                if not self.graph.node_exists(node_id):
                    continue
                # Try directed first (fast), then undirected
                hops = self.graph.hop_distance(node_id, cand_node)
                if hops >= 1_000_000:
                    try:
                        import networkx as _nx  # pylint: disable=import-outside-toplevel
                        hops = _nx.shortest_path_length(g_undirected, node_id, cand_node)
                    except Exception:  # pylint: disable=broad-except
                        hops = 1_000_000
                if min_hops is None or hops < min_hops:
                    min_hops = hops
                    if min_hops == 0:
                        break  # exact match — no need to keep searching
            if min_hops == 0:
                break

        if min_hops is None or min_hops >= 1_000_000:
            return 0.0
        return 1.0 / (1.0 + min_hops)

    @staticmethod
    def _behaviour_score(
        candidate: dict,
        all_counts: dict[str, float],
        max_count: float,
    ) -> float:
        """log(1 + count) / log(1 + max_count) → [0, 1]."""
        if max_count <= 0:
            return 0.0
        # use _symbol node id if available, else text as fallback key
        sym_id = candidate.get("_symbol") or candidate.get("text", "")[:80]
        raw = all_counts.get(sym_id, 0.0)
        return math.log(1.0 + raw) / math.log(1.0 + max_count)


# ── module-level convenience ──────────────────────────────────────────────────

# TTL cache for hybrid_retrieve: (query, top_k) → (result, timestamp)
_HYBRID_CACHE: dict[tuple, tuple] = {}
_HYBRID_CACHE_TTL = 300  # 5 minutes
_CACHE_HITS = 0
_CACHE_MISSES = 0


# Default 0.0 = no filtering. final_score on cold repos = 0.5*vector (graph+behaviour=0),
# so a 0.35 final_score gate requires vector_score>=0.70 which is unreachable on cold index.
# Let context_pack's _MIN_CODE_CONFIDENCE=0.25 gate handle quality at the pack layer.
_DEFAULT_MIN_SCORE: float = float(os.environ.get("COGNIREPO_MIN_RETRIEVAL_SCORE", "0.0"))


def hybrid_retrieve(query: str, top_k: int = 5, min_score: float | None = None) -> list[dict]:
    """
    Single entry point used by tools/retrieve_memory.py.
    Caches results for _HYBRID_CACHE_TTL seconds (default 5 min).
    Call invalidate_hybrid_cache() on file-change events to evict stale entries.

    min_score: filter results with final_score below this threshold.
               Default 0.0 (disabled) — set COGNIREPO_MIN_RETRIEVAL_SCORE env var to enable.
               If threshold > 0 but all results fall below it, returns full unfiltered list
               annotated with "_cold_fallback": True so callers can decide.
    """
    global _CACHE_HITS, _CACHE_MISSES  # pylint: disable=global-statement
    cache_key = (query, top_k)
    now = time.monotonic()
    cached = _HYBRID_CACHE.get(cache_key)
    if cached is not None:
        result, ts = cached
        if now - ts < _HYBRID_CACHE_TTL:
            _CACHE_HITS += 1
            return _apply_min_score(result, min_score)
    _CACHE_MISSES += 1
    result = HybridRetriever().retrieve(query, top_k)
    _HYBRID_CACHE[cache_key] = (result, now)
    return _apply_min_score(result, min_score)


def _apply_min_score(result: list[dict], min_score: float | None) -> list[dict]:
    """
    Apply min_score filter. If threshold > 0 but all results are below it
    (cold index scenario), return full list annotated with _cold_fallback=True
    rather than returning an empty list.
    """
    threshold = min_score if min_score is not None else _DEFAULT_MIN_SCORE
    if threshold <= 0 or not result:
        return result
    filtered = [r for r in result if r.get("final_score", 0.0) >= threshold]
    if not filtered:
        # Cold index: all scores below threshold — return everything with warning flag
        return [{**r, "_cold_fallback": True} for r in result]
    return filtered


def invalidate_hybrid_cache() -> None:
    """Evict all cached results. Call this on any file-change event."""
    _HYBRID_CACHE.clear()


def cache_stats() -> dict:
    """Return cache hit/miss counts for cognirepo doctor."""
    return {"hits": _CACHE_HITS, "misses": _CACHE_MISSES}


# ── episodic BM25 filter ──────────────────────────────────────────────────────

def episodic_bm25_filter(
    query: str,
    time_range: tuple[str, str] | None = None,
    top_k: int = 10,
) -> list[dict]:
    """
    BM25-ranked keyword search over the episodic event log.

    Uses the _bm25 package (C++ extension when built, pure-Python fallback
    otherwise) — the backend is transparent to callers.

    query      — free-text search string
    time_range — optional (iso_start, iso_end) to restrict events by timestamp
    top_k      — max events to return
    """
    events = get_history(limit=10_000)

    if time_range:
        start_str, end_str = time_range
        events = [
            ev for ev in events
            if start_str <= ev.get("time", "") <= end_str
        ]

    if not events:
        return []

    # Build a BM25 corpus from the event log
    # Document text = event string + serialised metadata for richer matching
    docs = [
        _Document(
            id=ev.get("id", str(i)),
            text=ev.get("event", "") + " " + " ".join(
                str(v) for v in ev.get("metadata", {}).values()
            ),
        )
        for i, ev in enumerate(events)
    ]

    bm25 = _BM25()
    bm25.index(docs)
    ranked = bm25.search(query, top_k=top_k)

    if not ranked:
        return []

    # Map document ids back to event dicts
    id_to_event = {ev.get("id", str(i)): ev for i, ev in enumerate(events)}
    return [id_to_event[doc_id] for doc_id, _ in ranked if doc_id in id_to_event]
