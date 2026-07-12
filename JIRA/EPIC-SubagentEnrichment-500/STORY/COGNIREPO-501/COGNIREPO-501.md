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
