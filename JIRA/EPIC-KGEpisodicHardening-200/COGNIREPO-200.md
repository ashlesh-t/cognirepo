# COGNIREPO-200 — EPIC: Knowledge Graph & Episodic Memory Hardening (Phase 1) → v2.1.0

## Backstory
The two user-named focus areas. Post-audit (2026-07-11) the graph is structurally sound but
blind to its own integrity (stats() returns only counts) and missing three long-roadmapped
enrichments (similarity edges, Go call completion, dynamic-dispatch detection). Episodic memory
works but is fragmented: the "what happened" record is split across episodic.json,
sessions/*.json, and the behaviour store with no merged timeline, no rollup, and rotated history
that no search path reads. Evidence: `COGNIREPO-200-Discovery.md` (this folder) — required
reading. Full plan: `docs/planning/01-kg-episodic-hardening.md`.

## Description
Stories: 201 (graph integrity sweep + metrics into graph_stats/doctor), 202 (SIMILAR_TO edges
via FAISS k-NN at index time, config-gated), 203 (Go call-graph completion + DYNAMIC_DISPATCH
annotation), 204 (unified get_timeline API — or zero-token bootstrap digest — merging
sessions/episodes/decisions/errors with deterministic rollup; the data foundation Phase 2
reads), 205 (archive search, episodic embedding cache, auto-episodes for index-repo/org rewire).
Order: 201 → (202 ∥ 203) → 204 → 205. Requires EPIC-100 signed off (baseline 2.0.1;
D02's unique IDs are a hard prerequisite for 204/205).

## Acceptance criteria
1. graph_stats reports orphans/dangling-files/swept_at; doctor flags nonzero orphans.
2. SIMILAR_TO edges exist for semantically-near symbols (cosine ≥ threshold, capped/node),
   visible via subgraph, gated by indexing.similarity_edges.
3. Go fixture: who_calls resolves ≥90% of a hand-verified caller list; registry-pattern fixture
   nodes carry dispatch:"dynamic".
4. One call returns the merged chronological timeline + human-readable rollup; archived events
   included on request.
5. Full pytest green; existing tool outputs unchanged except documented additive keys.

## Notes
Version 2.1.0. Ground Rule 3: 204 must record its measured manifest-token cost (~140) or ship
as the zero-token bootstrap digest. All retrieval stays behind intelligence/retrieval/hybrid.py.
