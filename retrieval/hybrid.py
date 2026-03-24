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

import numpy as np

from graph.behaviour_tracker import BehaviourTracker
from graph.graph_utils import extract_entities_from_text, make_node_id
from graph.knowledge_graph import KnowledgeGraph
from indexer.ast_indexer import ASTIndexer
from memory.embeddings import get_model
from memory.episodic_memory import get_history
from vector_db.local_vector_db import LocalVectorDB

CONFIG_FILE = ".cognirepo/config.json"
DEFAULT_WEIGHTS = {"vector": 0.5, "graph": 0.3, "behaviour": 0.2}


def _load_weights() -> dict[str, float]:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            w = cfg.get("retrieval_weights", DEFAULT_WEIGHTS)
            total = sum(w.values())
            if abs(total - 1.0) > 1e-6:
                raise ValueError(f"retrieval_weights must sum to 1.0, got {total:.4f}")
            return w
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULT_WEIGHTS


class HybridRetriever:
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
        """1 / (1 + min_hop_distance) across all query entities → [0, 1]."""
        if not query_entities or self.graph.G.number_of_nodes() == 0:
            return 0.0

        # candidate node id: prefer explicit _symbol, fall back to text-derived
        cand_node = candidate.get("_symbol")
        if not cand_node:
            cand_node = f"concept::{candidate.get('text', '')[:40].lower()}"

        min_hops = None
        for entity in query_entities:
            # try multiple node ID forms for the entity
            for node_id in [
                entity,
                make_node_id("CONCEPT", entity),
                make_node_id("FILE", entity),
                f"symbol::{entity}",
            ]:
                if not self.graph.node_exists(node_id):
                    continue
                hops = self.graph.hop_distance(node_id, cand_node)
                if min_hops is None or hops < min_hops:
                    min_hops = hops

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

def hybrid_retrieve(query: str, top_k: int = 5) -> list[dict]:
    """
    Single entry point used by tools/retrieve_memory.py.
    Instantiates HybridRetriever on each call (acceptable for CLI use;
    for server use, keep one instance alive).
    """
    return HybridRetriever().retrieve(query, top_k)


# ── episodic BM25 filter ──────────────────────────────────────────────────────

def episodic_bm25_filter(
    query: str,
    time_range: tuple[str, str] | None = None,
    top_k: int = 10,
) -> list[dict]:
    """
    TF-ratio keyword match on the episodic event log.

    query      — search string (tokenized on whitespace)
    time_range — optional (iso_start, iso_end) to restrict events by timestamp
    top_k      — max events to return

    No external BM25 library needed at episodic log scale.
    Replace inner scorer with rank-bm25 if log exceeds ~10k events.
    """
    events = get_history(limit=10_000)

    if time_range:
        start_str, end_str = time_range
        filtered = []
        for ev in events:
            ts = ev.get("time", "")
            if start_str <= ts <= end_str:
                filtered.append(ev)
        events = filtered

    query_tokens = query.lower().split()
    if not query_tokens:
        return events[:top_k]

    scored: list[tuple[float, dict]] = []
    for ev in events:
        event_text = ev.get("event", "").lower()
        event_tokens = event_text.split()
        if not event_tokens:
            continue
        score = sum(event_tokens.count(t) for t in query_tokens) / len(event_tokens)
        if score > 0:
            scored.append((score, ev))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [ev for _, ev in scored[:top_k]]
