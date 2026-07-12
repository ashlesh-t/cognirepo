# COGNIREPO-500 Discovery — Sub-agent delegation as data enrichment (Phase 4)

Verified against HEAD (`146627d`, v2.0.0) on 2026-07-11.

---

## 1. Scope confirmation

The brief's framing is honest to the codebase: `interface/tools/` is stateless with no cross-tool
calls (CLAUDE.md), there is no process-spawning machinery anywhere in `interface/` or
`intelligence/`, and adding orchestration would be a new subsystem contradicting the layer
architecture. **Agreed scope: enrichment only** — CogniRepo annotates its existing context
surface with independence/parallelizability facts; the consuming Claude Code session decides
whether to delegate. No disagreement to register.

## 2. Existing surfaces to enrich

- `context_pack` (`interface/tools/context_pack.py`) — the flagship output. Docstring contract
  (`:218-231`): always returns 5 base keys incl. `"status": "ok" | "no_confident_match" |
  "index_empty"`; returns `code_hits` (AST, `source == "ast"`) and doc/memory hits split
  (`:276-278`). Hits carry file paths — the raw material for a graph-independence check.
- Graph primitives for independence: `data/graph/knowledge_graph.py` — `hop_distance()`
  (`:267-274`, `sys.maxsize` when disconnected), `shortest_path()` (`:276-281`),
  `get_neighbours()` (`:227-265`). Two files/symbols with no path (or distance > threshold)
  through IMPORTS/CALLS/DEFINED_IN edges are structurally independent — delegable.
- `dependency_graph` tool already exposes import relations per module (manifest schema in
  100-Discovery §2); `who_calls` gives call-graph reach.
- TODO detection: no existing TODO scanner in the indexer (grep for TODO extraction in
  `ast_indexer.py` — none; comments are not indexed as symbols). A TODO/FIXME scan would be new
  extraction logic in the indexer or a lightweight grep-at-pack-time — planning decision;
  pack-time grep over only the hit files keeps index schema unchanged.

## 3. Retrieval-path constraint

`intelligence/retrieval/hybrid.py` owns retrieval (CLAUDE.md); `context_pack` already flows
query → `hybrid_retrieve` (`hybrid.py:440`) → merge/score (`:276-346` graph scoring). The
independence annotation is *post-retrieval analysis of the hit set*, so it belongs in the
context-pack assembly layer (`interface/tools/context_pack.py`) calling graph read APIs — but
Ground Rule 2 says nothing calls the graph directly from tools. Two compliant designs:
a. Add the independence computation to `hybrid.py` (it already scores candidates against the
   graph at `:346-403`) and surface per-hit `component_id`/`independent_of` in its results.
b. Add a small `intelligence/retrieval/` helper the tool calls.
Discovery leans (a): the graph-adjacency knowledge is already there.

## 4. Output-token cost discipline

`context_pack` is the token-budgeted core product (`max_tokens` default 2000). The enrichment
must be a few dozen tokens (e.g. a `delegation_hints` array of {group, files, reason} only when
≥2 independent groups exist; omitted otherwise) — never a fixed-cost section. Zero new MCP tools
required → zero manifest-token growth (Ground Rule 3 clean).

## 5. Consumer contract

For the hint to change behavior, downstream docs must say what to do with it: CLAUDE.md tool
routing table gains one line ("context_pack returns delegation_hints — consider Task/subagent
delegation when groups ≥ 2"). This epic's deliverable is data + docs, not orchestration.
