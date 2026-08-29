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
import logging
import math
import os
import threading
import time

import numpy as np

from core._bm25 import BM25 as _BM25, Document as _Document
from data.graph.behaviour_tracker import BehaviourTracker
from data.graph.graph_utils import extract_entities_from_text, make_node_id
from data.graph.knowledge_graph import KnowledgeGraph, EdgeType, NodeType
from intelligence.indexer.ast_indexer import ASTIndexer
from data.memory.circuit_breaker import CircuitOpenError
from data.memory.embeddings import encode_with_timeout
from data.memory.episodic_memory import get_history
from core.vector_db.local_vector_db import LocalVectorDB

from core.config.paths import get_path

log = logging.getLogger(__name__)


def _config_file() -> str:
    return get_path("config.json")
DEFAULT_WEIGHTS = {"vector": 0.5, "graph": 0.3, "behaviour": 0.2}

# A 1-hop link that is SIMILAR_TO-only (no CALLS/DEFINED_IN/IMPORTS/etc. also connecting the
# pair) is weaker relevance evidence than a real structural edge — discount it below the
# vanilla 1-hop score (0.5) but keep it above 2-hop (0.333). COGNIREPO-202.
_SIMILAR_TO_ONLY_DISCOUNT = 0.7

# COGNIREPO-501 — independence grouping. Only these edge types count as "structurally
# connected" for delegation purposes; QUERIED_WITH/CO_OCCURS/SIMILAR_TO/RELATES_TO don't imply
# a subagent working on one hit would step on another's toes.
_STRUCTURAL_EDGE_TYPES = {EdgeType.IMPORTS, EdgeType.CALLS, EdgeType.CALLED_BY, EdgeType.DEFINED_IN}
_GROUPING_HOP_CAP = 3
# Hard latency/precision backstop — see _reachable_files docstring for why hop cap alone
# isn't sufficient on a real, densely-connected repo.
_GROUPING_MAX_VISITED = 30

# integrity_report() is O(nodes), documented as "< 1s on a medium repo" (COGNIREPO-201) — far too
# slow to run synchronously on every hybrid_retrieve() call. Cache the gate decision at module
# level with the same TTL as _HYBRID_CACHE rather than recomputing per query.
_INTEGRITY_CACHE_TTL = 300
# Calibrated empirically (not guessed) against integrity_report() on every real indexed repo in
# cognirepo_test_repo/, from 1.9k nodes (flask) to 77.7k nodes (moby/kubernetes): every one of
# them reported 0 orphans and 0-4 dangling files. These thresholds sit an order of magnitude
# above the worst healthy value observed, so a healthy repo — however large — never trips the
# gate; only a graph that's actually corrupt (predominantly orphaned/dangling) does. Re-run the
# calibration in the sweep below if these ever need revisiting.
_INTEGRITY_ORPHAN_THRESHOLD = 100
_INTEGRITY_DANGLING_THRESHOLD = 20
_integrity_gate_cache: dict = {"allowed": True, "ts": 0.0}
_integrity_gate_lock = threading.Lock()


def _compute_integrity_allowed(graph: KnowledgeGraph) -> bool:
    """The actual orphan/dangling-threshold decision, with no cache and no shared state.

    Split out of _grouping_allowed() so the decision logic is unit-testable in isolation
    from the TTL cache below — that cache is one module-level dict shared by every
    concurrent caller in the process (any HybridRetriever, in any thread), so a test call
    racing against a genuinely concurrent one (e.g. a different test's background thread)
    could observe THAT OTHER call's verdict rather than its own, no matter how the dict
    itself is isolated — the race is in the cache's check-then-act window, not the object
    identity. This function has none of that: same graph in, same answer out, always.
    """
    try:
        from core.config.paths import get_cognirepo_dir  # pylint: disable=import-outside-toplevel
        repo_root = os.path.dirname(os.path.abspath(get_cognirepo_dir()))
        report = graph.integrity_report(repo_root)
        n_orphans, n_dangling = len(report["orphans"]), len(report["dangling_files"])
        allowed = (
            n_orphans <= _INTEGRITY_ORPHAN_THRESHOLD
            and n_dangling <= _INTEGRITY_DANGLING_THRESHOLD
        )
        if not allowed:
            # Grouping is skipped silently otherwise — a corrupt graph shouldn't crash
            # retrieval, but a maintainer trying to explain "why do I never get
            # component_ids" needs a trace of *why* the gate tripped.
            log.warning(
                "hybrid: independence grouping disabled — orphans=%d (limit %d), "
                "dangling=%d (limit %d); graph likely corrupt, re-run `cognirepo index-repo`",
                n_orphans, _INTEGRITY_ORPHAN_THRESHOLD,
                n_dangling, _INTEGRITY_DANGLING_THRESHOLD,
            )
        return allowed
    except Exception as exc:  # pylint: disable=broad-except
        # Fail open — a broken integrity check shouldn't break retrieval — but still surface
        # it, since a silently-broken check would look identical to "graph is fine".
        log.debug("hybrid: integrity_report() failed, grouping gate fails open: %s", exc)
        return True


def _grouping_allowed(graph: KnowledgeGraph) -> bool:
    """True unless the graph's orphan/dangling counts exceed a corruption-level threshold —
    so integrity problems never masquerade as legitimate parallelism (COGNIREPO-501 AC3).

    TTL-caches _compute_integrity_allowed()'s result across calls — integrity_report() is
    O(nodes), too slow to run synchronously on every hybrid_retrieve() call (see module
    comments above). NOT keyed by graph/repo identity (see COGNIREPO-500-D01 addendum) —
    correct for the common single-repo-per-process case, a known gap for cross-repo calls.
    """
    now = time.monotonic()
    with _integrity_gate_lock:
        if now - _integrity_gate_cache["ts"] < _INTEGRITY_CACHE_TTL:
            return _integrity_gate_cache["allowed"]
    allowed = _compute_integrity_allowed(graph)
    with _integrity_gate_lock:
        _integrity_gate_cache["allowed"] = allowed
        _integrity_gate_cache["ts"] = now
    return allowed


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
        from core.vector_db.factory import get_vector_adapter  # pylint: disable=import-outside-toplevel
        self.weights = _load_weights()
        self.db = get_vector_adapter()
        self.graph = KnowledgeGraph()
        self.behaviour = BehaviourTracker(self.graph)
        self.indexer = ASTIndexer(graph=self.graph)
        self.indexer.load()
        # Cache undirected view once — to_undirected() is O(V+E) and was
        # previously called once per candidate per query (up to 20× per retrieve).
        self._undirected = self.graph.G.to_undirected()

    # ── public API ────────────────────────────────────────────────────────────

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Return top_k results ranked by hybrid score.

        Each result dict contains:
          text, importance, source, final_score,
          vector_score, graph_score, behaviour_score
        """
        if len(query) > MAX_QUERY_LEN:
            raise ValueError(
                f"Query too long ({len(query):,} chars). "
                f"Maximum: {MAX_QUERY_LEN:,}. "
                "Truncate or set COGNIREPO_MAX_QUERY_LEN to override."
            )
        try:
            query_vector = encode_with_timeout(query).astype("float32")
        except CircuitOpenError:
            # Embedding unavailable — degrade gracefully to BM25+AST exact only
            return self._bm25_only_retrieve(query, top_k)

        # 1. wider vector net before re-ranking (semantic memory backend)
        # Fetch top_k*6 so that user-stored memories (which may rank lower than
        # many auto-ingested doc chunks by raw vector similarity) are included
        # in the candidate pool before importance-weighted re-ranking.
        vector_candidates = self._vector_retrieve(query_vector, top_k * 6)

        # 2. AST reverse-index exact lookup (entity names extracted from query)
        entities = extract_entities_from_text(query)
        ast_exact_candidates = self._ast_retrieve(entities)

        # 3. AST FAISS semantic search — works on fresh repos with no stored memories.
        #    This is the primary code-search path when the semantic memory is cold.
        ast_faiss_candidates = self._ast_faiss_retrieve(query_vector, top_k * 2)

        # 4. merge + dedup (AST exact overrides FAISS when same symbol; vector_score
        #    from FAISS is promoted to exact candidates that had score=0.0)
        all_candidates = self._merge_candidates(
            vector_candidates, ast_exact_candidates, ast_faiss_candidates
        )

        if not all_candidates:
            return []

        # 5. score
        all_counts = self.behaviour.get_all_scores()
        scored = self._score_candidates(all_candidates, entities, all_counts)

        # 6. sort + truncate
        scored.sort(key=lambda x: x["final_score"], reverse=True)
        top = scored[:top_k]

        # 6b. independence grouping (COGNIREPO-501) — annotates component_id in place,
        # never reorders or rescores; strips its own internal "_symbol" field when done.
        top = self._annotate_independence_groups(top)

        # 7. record query for user-behaviour profiling (never breaks retrieval)
        try:
            self.behaviour.record_query(
                query_id=str(abs(hash(query))),
                query_text=query,
                retrieved_symbols=[c.get("source", "") for c in top],
                faiss_rows=None,
            )
            self.behaviour.save()
        except Exception:  # pylint: disable=broad-except
            pass

        return top

    def _bm25_only_retrieve(self, query: str, top_k: int) -> list[dict]:
        """BM25 + AST exact fallback used when embeddings are unavailable (circuit open)."""
        entities = extract_entities_from_text(query)
        ast_candidates = self._ast_retrieve(entities)
        # Score purely by AST exact match (score=1.0) + simple keyword overlap
        results = []
        q_tokens = set(query.lower().split())
        for c in ast_candidates:
            text_tokens = set(c.get("text", "").lower().split())
            overlap = len(q_tokens & text_tokens) / max(len(q_tokens), 1)
            results.append({**c, "final_score": overlap, "retrieval_mode": "bm25_fallback"})
        results.sort(key=lambda x: x["final_score"], reverse=True)
        return results[:top_k]

    # ── private helpers ───────────────────────────────────────────────────────

    def _vector_retrieve(self, query_vector: np.ndarray, k: int) -> list[dict]:
        """Search semantic backend; converts distance/score to [0,1] range."""
        # Use count() to be backend-agnostic
        if self.db.count() == 0:
            return []
        actual_k = min(k, self.db.count())
        raw = self.db.search_with_scores(query_vector, actual_k)
        results = []
        for r in raw:
            # LocalVectorDB returns distance, ChromaAdapter returns distance but
            # both populate 'combined_score' if available or we compute here.
            # We standardize on distance-to-score logic for the hybrid mix.
            dist = r.get("l2_distance", 2.0)
            results.append({
                "text": r.get("text", ""),
                "importance": r.get("importance", 0.5),
                # COGNIREPO-D07: preserve the real stored metadata source
                # (e.g. "memory", "interaction_style", "symbol", "init_doc")
                # instead of the previous hardcoded "semantic" label, which
                # discarded it for every vector-backend hit.
                "source": r.get("source", "memory"),
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

    def _ast_faiss_retrieve(self, query_vector: np.ndarray, k: int) -> list[dict]:
        """
        Semantic FAISS search over AST-indexed code symbols.

        Unlike _ast_retrieve() which does exact entity-name lookup, this queries
        the AST FAISS index directly — works on fresh repos where no memories have
        been stored yet and extract_entities_from_text() returns nothing.

        Results use source="ast" and the same text format as _ast_retrieve so they
        flow correctly through context_pack's window-extraction and confidence gate.
        """
        if self.indexer.faiss_index is None or self.indexer.faiss_index.ntotal == 0:
            return []

        fetch_k = min(k * 2, self.indexer.faiss_index.ntotal)
        distances, ids = self.indexer.faiss_index.search(
            np.array([query_vector], dtype="float32"), fetch_k
        )

        results: list[dict] = []
        seen: set[str] = set()
        for dist, fid in zip(distances[0], ids[0]):
            if fid < 0 or fid >= len(self.indexer.faiss_meta):
                continue
            meta = self.indexer.faiss_meta[fid]
            # include file_summary entries — they answer "what does X.py do?" queries

            file_path = meta.get("file", "")
            name = meta.get("name", "")
            line = meta.get("start_line", -1)
            sym_type = meta.get("type", "SYMBOL")
            doc = meta.get("docstring", "")

            key = f"{file_path}::{name}"
            if key in seen:
                continue
            seen.add(key)

            text = f"{sym_type} {name} in {file_path}:{line}" + (f" — {doc}" if doc else "")
            raw_score = max(0.0, 1.0 - float(dist) / 2.0)
            # Weight from crawl: 1.0=direct, 0.75=hop-2, 0.5=indirect
            crawl_weight = float(meta.get("weight", 1.0))
            score = raw_score * crawl_weight

            results.append({
                "text": text,
                "importance": 0.6,
                "source": "ast",
                "vector_score": score,
                "_id": key,
                "_symbol": make_node_id(sym_type, name, file_path),
                "_crawl_weight": crawl_weight,
            })
            if len(results) >= k:
                break

        return results

    def _merge_candidates(
        self,
        vector_candidates: list[dict],
        ast_exact: list[dict],
        ast_faiss: list[dict] | None = None,
    ) -> list[dict]:
        """
        Deduplicate by _id across all three candidate lists.

        Priority: vector_candidates > ast_exact > ast_faiss.
        When the same symbol appears in multiple lists, the highest vector_score wins
        so FAISS scores promote exact-match candidates that had vector_score=0.0.
        """
        merged: dict[str, dict] = {}
        for c in vector_candidates:
            merged[c["_id"]] = c
        for c in ast_exact:
            existing = merged.get(c["_id"])
            if existing is None:
                merged[c["_id"]] = c
            elif c.get("vector_score", 0.0) > existing.get("vector_score", 0.0):
                merged[c["_id"]] = {**existing, "vector_score": c["vector_score"]}
        for c in (ast_faiss or []):
            existing = merged.get(c["_id"])
            if existing is None:
                merged[c["_id"]] = c
            elif c.get("vector_score", 0.0) > existing.get("vector_score", 0.0):
                # Promote the vector_score but keep other fields from the earlier entry
                merged[c["_id"]] = {**existing, "vector_score": c["vector_score"]}
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
            importance = c.get("importance", 0.5)
            # Cold-graph renormalization: when graph and behaviour are both zero
            # (fresh index, no behaviour history), blend vector similarity with
            # importance so explicitly stored memories (importance≈0.88) rank above
            # auto-ingested doc chunks (importance=0.6) even when vector scores are close.
            if g_score == 0.0 and b_score == 0.0:
                final = v_score * 0.7 + importance * 0.3
            else:
                # Warm path: standard weighted formula + importance as a small boost.
                # Scale existing weights to 0.85 so importance (0.15) slots in cleanly.
                final = (
                    self.weights["vector"] * v_score
                    + self.weights["graph"] * g_score
                    + self.weights["behaviour"] * b_score
                ) * 0.85 + importance * 0.15
            result = dict(c)
            result.update({
                "final_score": round(final, 4),
                "vector_score": round(v_score, 4),
                "graph_score": round(g_score, 4),
                "behaviour_score": round(b_score, 4),
            })
            result.pop("_id", None)
            # NOTE: "_symbol" is intentionally kept here (unlike "_id") — retrieve()'s
            # independence-grouping pass (COGNIREPO-501) needs it on the truncated top-k and
            # strips it itself before returning, so the final output shape is unchanged.
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

        g_undirected = self._undirected

        min_hops = None
        best_entity_node = None
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
                    best_entity_node = node_id
                    if min_hops == 0:
                        break  # exact match — no need to keep searching
            if min_hops == 0:
                break

        if min_hops is None or min_hops >= 1_000_000:
            return 0.0
        score = 1.0 / (1.0 + min_hops)
        if min_hops == 1 and best_entity_node and self._is_similar_to_only_link(best_entity_node, cand_node):
            score *= _SIMILAR_TO_ONLY_DISCOUNT
        return score

    def _is_similar_to_only_link(self, a: str, b: str) -> bool:
        """True if the only edge(s) directly connecting a and b are SIMILAR_TO."""
        edge_ab = self.graph.G.get_edge_data(a, b)
        edge_ba = self.graph.G.get_edge_data(b, a)
        rels = [e.get("rel") for e in (edge_ab, edge_ba) if e]
        return bool(rels) and all(r == EdgeType.SIMILAR_TO for r in rels)

    def _reachable_files(self, start_node: str) -> set[str]:
        """Bounded (hop cap _GROUPING_HOP_CAP, visited-node cap _GROUPING_MAX_VISITED)
        undirected BFS from start_node, traversing only _STRUCTURAL_EDGE_TYPES edges. Returns
        the set of file paths reached — FILE node IDs are themselves the file path
        (graph_utils.make_node_id); FUNCTION/CLASS nodes carry a 'file' attr. COGNIREPO-501.

        The visited-node cap exists because hop-cap-3 alone is not enough on a real,
        densely-connected repo: measured on cognirepo_test_repo/medium/ansible (17.6k nodes,
        96.5k edges), an unbounded hop-3 BFS from a single symbol reached 700-900 files through
        common hub utility/test files in 9-16ms each — blowing the <10ms/k<=10 budget (AC4) and
        making almost every hit look "connected" through shared infrastructure, defeating the
        whole point of the grouping (a hub-adjacent hit isn't meaningfully coupled to everything
        the hub touches). Stopping BFS once the cap is hit trades a small false-independence
        risk (two truly-connected-only-via-a-huge-hub files might get different component_ids)
        for bounded latency and groups that actually reflect direct coupling — the same
        precautionary direction as the integrity gate (COGNIREPO-501 Analyze correction).
        """
        g = self.graph.G
        if not g.has_node(start_node):
            return set()
        from collections import deque  # pylint: disable=import-outside-toplevel
        visited = {start_node}
        queue = deque([(start_node, 0)])
        files: set[str] = set()

        def _record(node: str) -> None:
            data = g.nodes[node]
            if data.get("type") == NodeType.FILE:
                files.add(node)
            elif data.get("file"):
                files.add(data["file"])

        _record(start_node)
        while queue:
            if len(visited) >= _GROUPING_MAX_VISITED:
                break
            current, hops = queue.popleft()
            if hops >= _GROUPING_HOP_CAP:
                continue
            neighbours = set(g.successors(current)) | set(g.predecessors(current))
            for nxt in neighbours:
                if len(visited) >= _GROUPING_MAX_VISITED:
                    break
                if nxt in visited:
                    continue
                edge_fwd = g.get_edge_data(current, nxt) or {}
                edge_bwd = g.get_edge_data(nxt, current) or {}
                rels = {edge_fwd.get("rel"), edge_bwd.get("rel")}
                if not rels & _STRUCTURAL_EDGE_TYPES:
                    continue
                visited.add(nxt)
                _record(nxt)
                queue.append((nxt, hops + 1))
        return files

    def _annotate_independence_groups(self, top: list[dict]) -> list[dict]:
        """Post-score pass (COGNIREPO-501): union-find hits whose files are reachable from one
        another through structural edges only, hop-capped. When the integrity gate blocks
        grouping (_grouping_allowed is False), no 'component_id' is added at all — every dict
        stays exactly as _score_candidates produced it (AC2 golden-identical behavior).
        Otherwise every hit with a resolvable '_symbol' gets a 'component_id' — equal for hits
        that turn out connected (AC1's "add one edge -> same id"), distinct otherwise. Hits with
        no resolvable symbol (e.g. memory-only candidates with no graph representation) get no
        key. Always strips the internal '_symbol' field before returning, matching pre-501
        output shape."""
        if not _grouping_allowed(self.graph):
            for r in top:
                r.pop("_symbol", None)
            return top

        # union-find over hit indices, keyed by reachable-file-set overlap
        parent = list(range(len(top)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i: int, j: int) -> None:
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[rj] = ri

        reachable = [
            self._reachable_files(r["_symbol"]) if r.get("_symbol") else set()
            for r in top
        ]
        for i in range(len(top)):
            for j in range(i + 1, len(top)):
                if reachable[i] & reachable[j]:
                    union(i, j)

        groupable_roots = sorted({find(i) for i, r in enumerate(top) if r.get("_symbol")})
        root_to_id = {root: f"g{n}" for n, root in enumerate(groupable_roots)}
        for i, r in enumerate(top):
            symbol = r.pop("_symbol", None)
            if symbol:
                r["component_id"] = root_to_id[find(i)]
        return top

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
_CACHE_LOCK = threading.Lock()

# In-flight dedup: N concurrent misses for the same key → 1 ASTIndexer.load()
# The first miss computes the result; subsequent misses wait on the Event.
_IN_FLIGHT: dict[tuple, threading.Event] = {}
_IN_FLIGHT_LOCK = threading.Lock()


# Default 0.0 = no filtering. final_score on cold repos = 0.5*vector (graph+behaviour=0),
# so a 0.35 final_score gate requires vector_score>=0.70 which is unreachable on cold index.
# Let context_pack's _MIN_CODE_CONFIDENCE=0.25 gate handle quality at the pack layer.
_DEFAULT_MIN_SCORE: float = float(os.environ.get("COGNIREPO_MIN_RETRIEVAL_SCORE", "0.0"))
MAX_QUERY_LEN: int = int(os.environ.get("COGNIREPO_MAX_QUERY_LEN", "50000"))


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
    # Include the active cognirepo dir in the cache key so that org_wide_search
    # switching _CTX_DIR across repos doesn't serve one repo's results to another.
    from core.config.paths import _CTX_DIR as _ctx  # pylint: disable=import-outside-toplevel
    cache_key = (query, top_k, _ctx.get(""))
    now = time.monotonic()

    with _CACHE_LOCK:
        cached = _HYBRID_CACHE.get(cache_key)
        if cached is not None:
            result, ts = cached
            if now - ts < _HYBRID_CACHE_TTL:
                _CACHE_HITS += 1
                try:
                    from core.metrics import CACHE_HITS as _CH  # pylint: disable=import-outside-toplevel
                    _CH.set(_CACHE_HITS)
                except Exception:  # pylint: disable=broad-except
                    pass
                return _apply_min_score(result, min_score)
        _CACHE_MISSES += 1
        try:
            from core.metrics import CACHE_MISSES as _CM  # pylint: disable=import-outside-toplevel
            _CM.set(_CACHE_MISSES)
        except Exception:  # pylint: disable=broad-except
            pass

    # In-flight dedup: if another thread is already computing this key, wait for it
    # rather than running N redundant ASTIndexer.load() calls in parallel.
    with _IN_FLIGHT_LOCK:
        existing_event = _IN_FLIGHT.get(cache_key)
        if existing_event is not None:
            waiter = existing_event
        else:
            waiter = None
            done_event = threading.Event()
            _IN_FLIGHT[cache_key] = done_event

    if waiter is not None:
        waiter.wait(timeout=30)
        # Re-check cache — the computing thread has stored the result by now
        with _CACHE_LOCK:
            cached = _HYBRID_CACHE.get(cache_key)
            if cached is not None:
                result, _ = cached
                return _apply_min_score(result, min_score)
        # Fallback: compute ourselves if result still missing (e.g. timeout)
        return _apply_min_score(HybridRetriever().retrieve(query, top_k), min_score)

    # We are the designated computing thread for this key.
    try:
        result = HybridRetriever().retrieve(query, top_k)
        now = time.monotonic()
        with _CACHE_LOCK:
            _HYBRID_CACHE[cache_key] = (result, now)
    except CircuitOpenError:
        # Don't cache degraded results; signal caller with structured response
        with _IN_FLIGHT_LOCK:
            _IN_FLIGHT.pop(cache_key, None)
        done_event.set()
        return [{"status": "circuit_open", "sections": [], "token_count": 0,
                 "hint": "CogniRepo server is under memory pressure. "
                         "Run: cognirepo server restart"}]
    finally:
        with _IN_FLIGHT_LOCK:
            _IN_FLIGHT.pop(cache_key, None)
        done_event.set()  # wake all waiters

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
    with _CACHE_LOCK:
        _HYBRID_CACHE.clear()
    # Do not clear _IN_FLIGHT — in-progress computations should complete normally.


def cache_stats() -> dict:
    """Return cache hit/miss counts for cognirepo doctor."""
    with _CACHE_LOCK:
        return {"hits": _CACHE_HITS, "misses": _CACHE_MISSES}


def is_index_cold() -> bool:
    """Return True when the configured vector backend has no vectors."""
    try:
        from core.vector_db.factory import get_vector_adapter  # pylint: disable=import-outside-toplevel
        return get_vector_adapter().count() == 0
    except Exception:  # pylint: disable=broad-except
        return False


# Keep is_faiss_cold as alias for backward compat
is_faiss_cold = is_index_cold


# ── episodic BM25 filter ──────────────────────────────────────────────────────

# Mtime-keyed cache: rebuild only when episodic.json changes on disk.
_BM25_CACHE: dict = {"mtime": -1.0, "bm25": None, "events": None}
_BM25_LOCK = threading.Lock()


def _get_cached_bm25() -> tuple:
    """Return (bm25, events, id_to_event) rebuilding only when episodic file changes."""
    from core.config.paths import get_path  # pylint: disable=import-outside-toplevel
    ep_file = get_path("episodic/episodic.json")
    try:
        mtime = os.path.getmtime(ep_file)
    except FileNotFoundError:
        mtime = 0.0

    with _BM25_LOCK:
        if _BM25_CACHE["mtime"] == mtime and _BM25_CACHE["bm25"] is not None:
            return _BM25_CACHE["bm25"], _BM25_CACHE["events"]

        events = get_history(limit=10_000)
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
        if docs:
            bm25.index(docs)
        _BM25_CACHE["mtime"] = mtime
        _BM25_CACHE["bm25"] = bm25
        _BM25_CACHE["events"] = events
        return bm25, events


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
    bm25, events = _get_cached_bm25()

    if time_range:
        start_str, end_str = time_range
        filtered_events = [
            ev for ev in events
            if start_str <= ev.get("time", "") <= end_str
        ]
        # Rebuild BM25 from the filtered subset so scores reflect only in-range events.
        # Using the full-corpus BM25 here would return doc_ids outside the window.
        if len(filtered_events) != len(events):
            events = filtered_events
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
            if docs:
                bm25.index(docs)
        else:
            events = filtered_events

    if not events:
        return []

    ranked = bm25.search(query, top_k=top_k)

    if not ranked:
        return []

    # Map document ids back to event dicts
    id_to_event = {ev.get("id", str(i)): ev for i, ev in enumerate(events)}
    return [id_to_event[doc_id] for doc_id, _ in ranked if doc_id in id_to_event]
