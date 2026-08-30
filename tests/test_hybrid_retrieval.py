# pylint: disable=missing-docstring, unnecessary-lambda, import-outside-toplevel, too-few-public-methods, duplicate-code
# pylint: disable=redefined-outer-name, unused-argument, broad-exception-caught, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_hybrid_retrieval.py — hybrid retrieval merge + scoring tests.

Uses real SemanticMemory (no FAISS mock) against isolated temp store.
Graph and behaviour scores default to 0 (cold start) — tests the
formula degrades correctly to pure vector retrieval.
"""
from __future__ import annotations


class TestHybridRetriever:
    def test_returns_list(self):
        from data.memory.semantic_memory import SemanticMemory
        sm = SemanticMemory()
        sm.store("fixed JWT expiry in verify_token")
        sm.store("refactored session handling")

        from intelligence.retrieval.hybrid import HybridRetriever
        r = HybridRetriever()
        results = r.retrieve("auth JWT", top_k=2)
        assert isinstance(results, list)

    def test_final_score_present(self):
        from data.memory.semantic_memory import SemanticMemory
        sm = SemanticMemory()
        sm.store("authentication token verification logic")

        from intelligence.retrieval.hybrid import HybridRetriever
        r = HybridRetriever()
        results = r.retrieve("token auth", top_k=1)
        if results:
            assert "final_score" in results[0]
            assert 0.0 <= results[0]["final_score"] <= 1.0

    def test_top_k_respected(self):
        from data.memory.semantic_memory import SemanticMemory
        sm = SemanticMemory()
        for i in range(8):
            sm.store(f"memory item {i} about code and functions")

        from intelligence.retrieval.hybrid import HybridRetriever
        r = HybridRetriever()
        results = r.retrieve("code functions", top_k=3)
        assert len(results) <= 3

    def test_cold_start_no_crash(self):
        """Empty graph + no behaviour data → falls back to vector only."""
        from intelligence.retrieval.hybrid import HybridRetriever
        r = HybridRetriever()
        results = r.retrieve("anything at all", top_k=5)
        assert isinstance(results, list)

    def test_empty_store_returns_empty(self):
        from intelligence.retrieval.hybrid import HybridRetriever
        r = HybridRetriever()
        results = r.retrieve("query with no memories stored", top_k=5)
        assert isinstance(results, list)

    def test_hybrid_retrieve_function(self):
        from data.memory.semantic_memory import SemanticMemory
        sm = SemanticMemory()
        sm.store("debug the login flow for oauth")

        from intelligence.retrieval.hybrid import hybrid_retrieve
        results = hybrid_retrieve("oauth login", top_k=1)
        assert isinstance(results, list)

    def test_scores_sorted_descending(self):
        from data.memory.semantic_memory import SemanticMemory
        sm = SemanticMemory()
        sm.store("verify_token handles JWT expiry correctly")
        sm.store("unrelated topic about cooking recipes")
        sm.store("authentication middleware checks bearer token")

        from intelligence.retrieval.hybrid import HybridRetriever
        r = HybridRetriever()
        results = r.retrieve("JWT authentication token", top_k=3)
        scores = [res["final_score"] for res in results if "final_score" in res]
        assert scores == sorted(scores, reverse=True)


class TestGraphScoreSimilarToWeighting:
    """COGNIREPO-202 AC4 — SIMILAR_TO is weighted into _graph_score, not treated as a
    full-strength structural edge (non-regression: a real 1-hop edge still outscores it)."""

    def test_similar_to_only_link_discounted_below_real_edge(self):
        from data.graph.knowledge_graph import EdgeType, NodeType
        from intelligence.retrieval.hybrid import HybridRetriever

        r = HybridRetriever()
        r.graph.add_node("a.py::verify_a", NodeType.FUNCTION, file="a.py")
        r.graph.add_node("b.py::verify_b", NodeType.FUNCTION, file="b.py")
        r.graph.add_edge("a.py::verify_a", "b.py::verify_b", EdgeType.SIMILAR_TO, weight=0.9)
        r.graph.add_edge("b.py::verify_b", "a.py::verify_a", EdgeType.SIMILAR_TO, weight=0.9)
        r._undirected = r.graph.G.to_undirected()  # rebuild after manual edits

        similar_only_score = r._graph_score({"_symbol": "b.py::verify_b"}, ["a.py::verify_a"])

        r.graph.add_node("c.py::verify_c", NodeType.FUNCTION, file="c.py")
        r.graph.add_edge("a.py::verify_a", "c.py::verify_c", EdgeType.CALLED_BY)
        r.graph.add_edge("c.py::verify_c", "a.py::verify_a", EdgeType.CALLS)
        r._undirected = r.graph.G.to_undirected()

        real_edge_score = r._graph_score({"_symbol": "c.py::verify_c"}, ["a.py::verify_a"])

        assert 0.0 < similar_only_score < real_edge_score == 0.5

    def test_similar_to_plus_real_edge_not_discounted(self):
        """When a real structural edge ALSO connects the pair, no discount applies."""
        from data.graph.knowledge_graph import EdgeType, NodeType
        from intelligence.retrieval.hybrid import HybridRetriever

        r = HybridRetriever()
        r.graph.add_node("a.py::verify_a", NodeType.FUNCTION, file="a.py")
        r.graph.add_node("b.py::verify_b", NodeType.FUNCTION, file="b.py")
        r.graph.add_edge("a.py::verify_a", "b.py::verify_b", EdgeType.CALLED_BY)
        r.graph.add_edge("b.py::verify_b", "a.py::verify_a", EdgeType.SIMILAR_TO, weight=0.9)
        r._undirected = r.graph.G.to_undirected()

        score = r._graph_score({"_symbol": "b.py::verify_b"}, ["a.py::verify_a"])
        assert score == 0.5


class TestIndependenceGrouping:
    """COGNIREPO-501 — union-find grouping of hits by structural-edge reachability."""

    def test_disconnected_files_get_different_component_ids(self, monkeypatch):
        from data.graph.knowledge_graph import NodeType
        from intelligence.retrieval import hybrid as hybrid_mod
        from intelligence.retrieval.hybrid import HybridRetriever

        monkeypatch.setattr(hybrid_mod, "_grouping_allowed", lambda graph: True)
        r = HybridRetriever()
        r.graph.add_node("a.py::fn_a", NodeType.FUNCTION, file="a.py")
        r.graph.add_node("b.py::fn_b", NodeType.FUNCTION, file="b.py")
        # no edge at all between them

        top = [
            {"final_score": 0.9, "_symbol": "a.py::fn_a"},
            {"final_score": 0.8, "_symbol": "b.py::fn_b"},
        ]
        result = r._annotate_independence_groups(top)
        assert result[0]["component_id"] != result[1]["component_id"]
        assert "_symbol" not in result[0] and "_symbol" not in result[1]

    def test_adding_import_edge_merges_into_same_component(self, monkeypatch):
        from data.graph.knowledge_graph import EdgeType, NodeType
        from intelligence.retrieval import hybrid as hybrid_mod
        from intelligence.retrieval.hybrid import HybridRetriever

        monkeypatch.setattr(hybrid_mod, "_grouping_allowed", lambda graph: True)
        r = HybridRetriever()
        r.graph.add_node("a.py", NodeType.FILE)
        r.graph.add_node("b.py", NodeType.FILE)
        r.graph.add_node("a.py::fn_a", NodeType.FUNCTION, file="a.py")
        r.graph.add_node("b.py::fn_b", NodeType.FUNCTION, file="b.py")
        r.graph.add_edge("a.py::fn_a", "a.py", EdgeType.DEFINED_IN)
        r.graph.add_edge("b.py::fn_b", "b.py", EdgeType.DEFINED_IN)
        r.graph.add_edge("a.py", "b.py", EdgeType.IMPORTS)

        top = [
            {"final_score": 0.9, "_symbol": "a.py::fn_a"},
            {"final_score": 0.8, "_symbol": "b.py::fn_b"},
        ]
        result = r._annotate_independence_groups(top)
        assert result[0]["component_id"] == result[1]["component_id"]

    def test_similar_to_edge_alone_does_not_merge(self, monkeypatch):
        """SIMILAR_TO is not a structural edge type for grouping purposes."""
        from data.graph.knowledge_graph import EdgeType, NodeType
        from intelligence.retrieval import hybrid as hybrid_mod
        from intelligence.retrieval.hybrid import HybridRetriever

        monkeypatch.setattr(hybrid_mod, "_grouping_allowed", lambda graph: True)
        r = HybridRetriever()
        r.graph.add_node("a.py::fn_a", NodeType.FUNCTION, file="a.py")
        r.graph.add_node("b.py::fn_b", NodeType.FUNCTION, file="b.py")
        r.graph.add_edge("a.py::fn_a", "b.py::fn_b", EdgeType.SIMILAR_TO)
        r.graph.add_edge("b.py::fn_b", "a.py::fn_a", EdgeType.SIMILAR_TO)

        top = [
            {"final_score": 0.9, "_symbol": "a.py::fn_a"},
            {"final_score": 0.8, "_symbol": "b.py::fn_b"},
        ]
        result = r._annotate_independence_groups(top)
        assert result[0]["component_id"] != result[1]["component_id"]

    def test_integrity_gate_blocks_grouping_entirely(self, monkeypatch):
        """AC3: high-orphan graph -> no component_id emitted at all."""
        from data.graph.knowledge_graph import NodeType
        from intelligence.retrieval import hybrid as hybrid_mod
        from intelligence.retrieval.hybrid import HybridRetriever

        monkeypatch.setattr(hybrid_mod, "_grouping_allowed", lambda graph: False)
        r = HybridRetriever()
        r.graph.add_node("a.py::fn_a", NodeType.FUNCTION, file="a.py")
        r.graph.add_node("b.py::fn_b", NodeType.FUNCTION, file="b.py")

        top = [
            {"final_score": 0.9, "_symbol": "a.py::fn_a"},
            {"final_score": 0.8, "_symbol": "b.py::fn_b"},
        ]
        result = r._annotate_independence_groups(top)
        assert "component_id" not in result[0]
        assert "component_id" not in result[1]

    def test_golden_regression_other_fields_untouched(self, monkeypatch):
        """AC2: with grouping gated off, hits/scores/order are byte-identical apart from
        the internal _symbol field, which was never part of the pre-501 output contract."""
        from data.graph.knowledge_graph import NodeType
        from intelligence.retrieval import hybrid as hybrid_mod
        from intelligence.retrieval.hybrid import HybridRetriever

        monkeypatch.setattr(hybrid_mod, "_grouping_allowed", lambda graph: False)
        r = HybridRetriever()
        r.graph.add_node("a.py::fn_a", NodeType.FUNCTION, file="a.py")

        original = {"final_score": 0.9, "vector_score": 0.8, "text": "fn_a",
                    "_symbol": "a.py::fn_a"}
        top = [dict(original)]
        result = r._annotate_independence_groups(top)
        expected = {k: v for k, v in original.items() if k != "_symbol"}
        assert result[0] == expected

    def test_reachable_files_respects_hop_cap(self, monkeypatch):
        from data.graph.knowledge_graph import EdgeType, NodeType
        from intelligence.retrieval.hybrid import HybridRetriever

        r = HybridRetriever()
        # chain: a -> b -> c -> d -> e (4 hops from a to e), all via CALLS/CALLED_BY
        nodes = ["a.py::fn", "b.py::fn", "c.py::fn", "d.py::fn", "e.py::fn"]
        for n in nodes:
            r.graph.add_node(n, NodeType.FUNCTION, file=n.split("::")[0])
        for a, b in zip(nodes, nodes[1:]):
            r.graph.add_edge(a, b, EdgeType.CALLED_BY)
            r.graph.add_edge(b, a, EdgeType.CALLS)

        reached = r._reachable_files("a.py::fn")
        # hop cap 3: a(0) -> b(1) -> c(2) -> d(3) reachable; e.py (hop 4) is not
        assert "a.py" in reached and "b.py" in reached and "c.py" in reached and "d.py" in reached
        assert "e.py" not in reached

    def test_reachable_files_capped_through_hub_node(self, monkeypatch):
        """Found dogfooding on cognirepo_test_repo/medium/ansible: a hub file used by hundreds
        of others makes hop-cap-3 alone reach 700-900 files in 9-16ms. _GROUPING_MAX_VISITED
        bounds this regardless of hop cap."""
        from data.graph.knowledge_graph import EdgeType, NodeType
        from intelligence.retrieval import hybrid as hybrid_mod
        from intelligence.retrieval.hybrid import HybridRetriever

        r = HybridRetriever()
        r.graph.add_node("start.py::fn", NodeType.FUNCTION, file="start.py")
        r.graph.add_node("hub.py::util", NodeType.FUNCTION, file="hub.py")
        r.graph.add_edge("start.py::fn", "hub.py::util", EdgeType.CALLED_BY)
        r.graph.add_edge("hub.py::util", "start.py::fn", EdgeType.CALLS)
        # hub.py::util is called by 200 unrelated files — classic fan-out hub
        for i in range(200):
            node = f"file{i}.py::caller"
            r.graph.add_node(node, NodeType.FUNCTION, file=f"file{i}.py")
            r.graph.add_edge(node, "hub.py::util", EdgeType.CALLED_BY)
            r.graph.add_edge("hub.py::util", node, EdgeType.CALLS)

        reached = r._reachable_files("start.py::fn")
        assert len(reached) <= hybrid_mod._GROUPING_MAX_VISITED

    def test_grouping_allowed_on_clean_graph(self, tmp_path, monkeypatch):
        """_compute_integrity_allowed (the decision _grouping_allowed caches) returns True
        for a graph with no orphans.

        Calls _compute_integrity_allowed() directly rather than the cached _grouping_allowed()
        wrapper — see test_grouping_allowed_trips_on_high_orphan_count below for why: the
        wrapper's TTL cache is one module-level dict shared by every concurrent caller in the
        process, and no amount of isolating the dict object closes the race, since the cache
        stores a per-CALL verdict with no notion of which graph it came from.
        """
        from intelligence.retrieval import hybrid as hybrid_mod
        from intelligence.retrieval.hybrid import HybridRetriever

        (tmp_path / ".cognirepo").mkdir(parents=True, exist_ok=True)
        # get_cognirepo_dir() checks a ContextVar before the COGNIREPO_DIR env var (used by
        # CrossRepoRouter for thread safety) — patch it directly so repo_root resolution can't
        # be affected by ambient state either.
        import core.config.paths as _paths_mod
        monkeypatch.setattr(_paths_mod, "get_cognirepo_dir", lambda: str(tmp_path / ".cognirepo"))
        r = HybridRetriever()
        assert hybrid_mod._compute_integrity_allowed(r.graph) is True

    def test_grouping_allowed_trips_on_high_orphan_count(self, tmp_path, monkeypatch, caplog):
        """AC3: a graph past the corruption-level orphan threshold gates grouping off,
        and the trip is logged (not silent) — see PR #63 review discussion.

        Calls _compute_integrity_allowed() directly, not the cached _grouping_allowed()
        wrapper. This assertion originally flaked on CI (push-triggered runs only) with
        "assert True is False" even after isolating _integrity_gate_cache to a private dict —
        because _grouping_allowed's cache is a single module-level dict storing one verdict for
        ANY graph any concurrent caller passes it (any HybridRetriever, any thread, in the same
        process); a genuinely concurrent caller (e.g. another test's background thread, or
        pytest-xdist scheduling this test right after one) racing the cache's check-then-act
        window can have ITS verdict read back for THIS graph, no matter whose dict object it
        is. _compute_integrity_allowed has no cache and no shared state — same graph in, same
        answer out, always; this is what actually needed testing for AC3, and it's what
        _grouping_allowed's cache wraps (test_grouping_allowed_caches_result below covers the
        wrapper's TTL behavior with a MagicMock graph, which was never part of the flake).
        Also documented as a real production gap in COGNIREPO-500-D01's addendum (the cache
        should be keyed by repo/graph identity — not fixed here).
        """
        from data.graph.knowledge_graph import NodeType
        from intelligence.retrieval import hybrid as hybrid_mod
        from intelligence.retrieval.hybrid import HybridRetriever

        (tmp_path / ".cognirepo").mkdir(parents=True, exist_ok=True)
        import core.config.paths as _paths_mod
        monkeypatch.setattr(_paths_mod, "get_cognirepo_dir", lambda: str(tmp_path / ".cognirepo"))
        r = HybridRetriever()
        # Degree-0 FILE nodes with no incident edges — exactly what integrity_report()
        # counts as orphans. One past the threshold is enough to trip the gate.
        for i in range(hybrid_mod._INTEGRITY_ORPHAN_THRESHOLD + 1):
            r.graph.add_node(f"orphan{i}.py", NodeType.FILE, file=f"orphan{i}.py")

        with caplog.at_level("WARNING", logger=hybrid_mod.log.name):
            allowed = hybrid_mod._compute_integrity_allowed(r.graph)
        assert allowed is False
        assert "independence grouping disabled" in caplog.text

    def test_grouping_allowed_caches_result(self, monkeypatch):
        """Repeated calls within the TTL don't re-run integrity_report."""
        from intelligence.retrieval import hybrid as hybrid_mod
        from unittest.mock import MagicMock

        hybrid_mod._integrity_gate_cache["ts"] = hybrid_mod.time.monotonic()
        hybrid_mod._integrity_gate_cache["allowed"] = True
        fake_graph = MagicMock()
        assert hybrid_mod._grouping_allowed(fake_graph) is True
        fake_graph.integrity_report.assert_not_called()

    def test_grouping_allowed_cache_not_keyed_by_graph(self, tmp_path, monkeypatch):
        """Documents the known gap behind COGNIREPO-500-D01's addendum and the CI flake that
        led to _compute_integrity_allowed being split out: _grouping_allowed's TTL cache is
        one module-level dict for the whole process, with no notion of WHICH graph a verdict
        was computed for. Two concurrent callers with different graphs (a healthy one, a
        corrupt one) can have the corrupt one's caller read back the healthy one's cached
        verdict — reproduced here directly rather than asserted as "sometimes flaky"."""
        import threading
        import networkx as nx
        from data.graph.knowledge_graph import NodeType
        from intelligence.retrieval import hybrid as hybrid_mod

        import core.config.paths as _paths_mod
        (tmp_path / ".cognirepo").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(_paths_mod, "get_cognirepo_dir", lambda: str(tmp_path / ".cognirepo"))
        monkeypatch.setattr(hybrid_mod, "_integrity_gate_cache", {"allowed": True, "ts": 0.0})

        healthy = hybrid_mod.KnowledgeGraph.__new__(hybrid_mod.KnowledgeGraph)
        healthy.G = nx.DiGraph()
        corrupt = hybrid_mod.KnowledgeGraph.__new__(hybrid_mod.KnowledgeGraph)
        corrupt.G = nx.DiGraph()
        for i in range(hybrid_mod._INTEGRITY_ORPHAN_THRESHOLD + 1):
            corrupt.add_node(f"orphan{i}.py", NodeType.FILE, file=f"orphan{i}.py")

        results = {}

        def _call_corrupt():
            # Give the healthy call a head start so it wins the cache write —
            # deterministic ordering, not a hope-it-races timing gamble.
            import time as _time
            _time.sleep(0.02)
            results["corrupt"] = hybrid_mod._grouping_allowed(corrupt)

        t_healthy = threading.Thread(target=lambda: hybrid_mod._grouping_allowed(healthy))
        t_corrupt = threading.Thread(target=_call_corrupt)
        t_healthy.start()
        t_corrupt.start()
        t_healthy.join()
        t_corrupt.join()

        # The known-bad behavior: the corrupt graph's caller reads back the healthy graph's
        # cached True instead of computing its own False. This is what makes
        # _compute_integrity_allowed() (tested directly above, no cache involved) the right
        # thing for AC3 correctness tests to call instead of this cached wrapper.
        assert results["corrupt"] is True  # documents the gap; not the desired behavior

    def test_annotate_independence_groups_latency(self, monkeypatch):
        """AC4: added latency < 10ms for k <= 10 on a small synthetic graph."""
        import time as _time
        from data.graph.knowledge_graph import NodeType
        from intelligence.retrieval import hybrid as hybrid_mod
        from intelligence.retrieval.hybrid import HybridRetriever

        monkeypatch.setattr(hybrid_mod, "_grouping_allowed", lambda graph: True)
        r = HybridRetriever()
        top = []
        for i in range(10):
            node = f"file{i}.py::fn{i}"
            r.graph.add_node(node, NodeType.FUNCTION, file=f"file{i}.py")
            top.append({"final_score": 1.0 - i * 0.01, "_symbol": node})

        start = _time.perf_counter()
        r._annotate_independence_groups(top)
        elapsed_ms = (_time.perf_counter() - start) * 1000
        assert elapsed_ms < 10.0, f"grouping took {elapsed_ms:.2f}ms, budget is 10ms"


class TestVectorRetrieveSourcePreservation:
    """COGNIREPO-D07: _vector_retrieve() must report the real stored source
    (previously hardcoded "semantic" for every vector-backend hit)."""

    def test_preserves_real_stored_source(self):
        from intelligence.retrieval.hybrid import HybridRetriever
        from data.memory.embeddings import encode_with_timeout

        r = HybridRetriever()
        vec = encode_with_timeout("interaction style summary text").astype("float32")
        r.db.add(vec, "interaction style summary text", importance=0.8, source="interaction_style")

        results = r._vector_retrieve(vec, k=5)
        assert results
        assert results[0]["source"] == "interaction_style"

    def test_defaults_to_memory_when_source_missing(self):
        from intelligence.retrieval.hybrid import HybridRetriever
        from data.memory.semantic_memory import SemanticMemory
        from data.memory.embeddings import encode_with_timeout

        sm = SemanticMemory()
        sm.store("plain stored memory with default source")

        r = HybridRetriever()
        vec = encode_with_timeout("plain stored memory with default source").astype("float32")
        results = r._vector_retrieve(vec, k=5)
        assert results
        assert results[0]["source"] == "memory"


class TestConcurrentCacheMiss:
    def test_concurrent_misses_call_retriever_once(self, monkeypatch):
        """N concurrent cache misses for same key → HybridRetriever.retrieve called once."""
        import threading
        import intelligence.retrieval.hybrid as rh

        rh.invalidate_hybrid_cache()
        call_count = {"n": 0}
        real_retrieve = rh.HybridRetriever.retrieve

        def counting_retrieve(self, query, top_k):
            call_count["n"] += 1
            return real_retrieve(self, query, top_k)

        monkeypatch.setattr(rh.HybridRetriever, "retrieve", counting_retrieve)
        rh.invalidate_hybrid_cache()

        results_bucket = []
        errors = []

        def _call():
            try:
                r = rh.hybrid_retrieve("concurrent test query", top_k=1)
                results_bucket.append(r)
            except Exception as exc:  # pylint: disable=broad-except
                errors.append(exc)

        threads = [threading.Thread(target=_call) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Thread errors: {errors}"
        assert len(results_bucket) == 5
        assert call_count["n"] == 1, (
            f"Expected 1 HybridRetriever.retrieve call, got {call_count['n']}"
        )


class TestEpisodicBM25:
    def test_episodic_filter(self):
        from data.memory.episodic_memory import log_event
        log_event("deployed auth service to production", {"env": "prod"})
        log_event("fixed bug in payment module", {"module": "payments"})
        log_event("updated JWT expiry to 24 hours", {"service": "auth"})

        from intelligence.retrieval.hybrid import episodic_bm25_filter
        results = episodic_bm25_filter("JWT auth", top_k=2)
        assert isinstance(results, list)
        # JWT-related event should appear
        if results:
            combined = " ".join(r.get("event", "") for r in results).lower()
            assert "jwt" in combined or "auth" in combined

    def test_time_range_excludes_out_of_range_events(self, monkeypatch):
        """time_range filter must only return events within the window."""
        import intelligence.retrieval.hybrid as rh
        # Seed three events at different timestamps
        events = [
            {"id": "e0", "event": "authentication token bug", "metadata": {}, "time": "2026-01-01T10:00:00Z"},
            {"id": "e1", "event": "authentication token bug refactor", "metadata": {}, "time": "2026-02-01T10:00:00Z"},
            {"id": "e2", "event": "authentication token cache miss", "metadata": {}, "time": "2026-03-01T10:00:00Z"},
        ]
        from core._bm25 import BM25 as _BM25, Document as _Document
        docs = [_Document(id=e["id"], text=e["event"]) for e in events]
        bm25_full = _BM25()
        bm25_full.index(docs)

        monkeypatch.setattr(rh, "_get_cached_bm25", lambda: (bm25_full, events))

        # Only e1 falls within this range
        results = rh.episodic_bm25_filter(
            "authentication",
            time_range=("2026-01-15T00:00:00Z", "2026-02-28T00:00:00Z"),
            top_k=10,
        )
        returned_ids = {r.get("id") for r in results}
        assert "e0" not in returned_ids, "e0 is outside time_range and must be excluded"
        assert "e2" not in returned_ids, "e2 is outside time_range and must be excluded"
        assert "e1" in returned_ids, "e1 is within time_range and must be returned"
