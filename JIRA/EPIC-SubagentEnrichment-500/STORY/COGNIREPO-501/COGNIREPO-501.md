# COGNIREPO-501 — Independence grouping in hybrid retrieval

Epic: COGNIREPO-500 · Branch: story/COGNIREPO-501 · Base: development

## Backstory
Grouping belongs where graph scoring already lives — intelligence/retrieval/hybrid.py
(_graph_score :346-403) — because CLAUDE.md forbids tools touching the graph directly. Graph
primitives available: hop_distance (knowledge_graph.py:267-274, sys.maxsize when disconnected),
shortest_path (:276-281), get_neighbours (:227-265). Two hit files with no path through
IMPORTS/CALLS/CALLED_BY/DEFINED_IN edges (hop cap ~3) are structurally independent. Evidence:
../../COGNIREPO-500-Discovery.md §2-§3.

## Description
Post-score pass in hybrid_retrieve (hybrid.py:440 path): union-find over the distinct files of
the top-k hits using bounded graph connectivity restricted to structural edge types; annotate
each result dict with component_id. Integrity gate: consult
KnowledgeGraph.integrity_report() (COGNIREPO-201) — when orphan/dangling counts exceed a
threshold, skip grouping entirely (emit no component_ids) so corruption never masquerades as
parallelism. Ranking/scores/status must be untouched.

## Acceptance criteria
1. Fixture: hits from two edge-disconnected modules → distinct component_ids; add one IMPORTS
   edge → same id.
2. Hits/scores/order byte-identical with the pass disabled (golden test).
3. High-orphan graph ⇒ no component_ids emitted.
4. Added latency on medium repo < 10 ms for k ≤ 10 (bounded BFS per file pair or single BFS per
   component seed).

## Risks / notes
- Use undirected reachability over the restricted edge set (CALLED_BY/CALLS are both present as
  directions — dedupe).

## Analyze correction (line drift + design decisions, verified at implementation HEAD)
Discovery-cited line numbers drifted: `_graph_score` now hybrid.py:355-410 (not :346-403),
`hop_distance`/`shortest_path`/`get_neighbours` now knowledge_graph.py:390/399/350 (not
:267-281/227-265), `hybrid_retrieve` entry now hybrid.py:461 (not :440) — same shape, only
`self._undirected = self.graph.G.to_undirected()` already cached in `__init__` for
`_graph_score`'s undirected fallback, but it covers ALL edge types, not the restricted
IMPORTS/CALLS/CALLED_BY/DEFINED_IN set this story needs — writing a dedicated bounded BFS
instead of reusing it.

Confirmed CALLS/CALLED_BY are both physically stored (`ast_indexer.py:1875-1876` — caller→callee
as CALLED_BY, callee→caller as CALLS, explicitly to avoid needing `predecessors()`), so directed
traversal already covers both call directions. IMPORTS and DEFINED_IN are stored in ONE direction
only (file→file, symbol→file) — true undirected reachability is required for those, matching the
ticket's own risk note.

`_symbol` (the candidate's graph node id) is popped from each result dict inside
`_score_candidates` (hybrid.py:350-351) BEFORE `retrieve()`'s "6. sort + truncate" step where the
post-score pass runs — deferred that pop to after grouping runs (inside the new
`_annotate_independence_groups`, on the truncated top-k only) rather than moving where grouping
happens, to keep the diff minimal and match "Ranking/scores/status must be untouched" exactly.

`KnowledgeGraph.integrity_report()`'s own docstring targets "< 1s on a medium repo" — running it
fresh on every `hybrid_retrieve()` call (itself constructing a new `HybridRetriever()` each time)
would blow the AC4 <10ms budget by two orders of magnitude. Caching the integrity gate result at
module level with the same 5-minute TTL as `_HYBRID_CACHE` (not a per-query call) resolves this —
consulting integrity_report() as the ticket specifies, just not synchronously per query.

Design decision not spelled out in the ticket: `component_id` is added ONLY when ≥2 distinct
components exist among the top-k hits (or omitted entirely when integrity-gated or everything is
one component) — this is what makes AC2's "byte-identical with the pass disabled" hold in the
common case without a separate on/off config flag: "disabled" = "no grouping opportunity found,"
not a config toggle.

**Revised after dogfooding on a real indexed repo** (`cognirepo_test_repo/medium/ansible`, 17.6k
nodes / 96.5k edges — an actual "medium" repo, not a toy): hop-cap-3 alone was NOT sufficient.
`_reachable_files` from a single symbol reached 700-900 files in 9-16ms via common hub
utility/test files, blowing AC4's <10ms/k≤10 budget outright and making nearly every hit look
"connected" through shared infrastructure — defeating the feature's purpose (a hit adjacent to a
widely-used hub isn't meaningfully coupled to everything that hub touches). Added a hard
visited-node safety cap (`_GROUPING_MAX_VISITED = 30`) — re-measured after the fix: 0.08-0.12ms
per BFS call on the same real repo/symbols, correct grouping preserved (verified the two
symbols still correctly landed in the same component via their real shared hub edge). Also
confirmed empirically: the integrity-gate check itself (`integrity_report()`, cold cache) costs
several ms on this graph size — this is expected and already amortized via the 5-minute cache
(warm-cache `_annotate_independence_groups` measured at 0.15ms for 2 hits), not a per-query cost
in steady state.
