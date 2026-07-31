# Phase 1 — Knowledge Graph & Episodic Memory Hardening → v2.1.0

**Epic:** COGNIREPO-200 (`JIRA/EPIC-KGEpisodicHardening-200/`). Evidence:
`JIRA/EPIC-KGEpisodicHardening-200/COGNIREPO-200-Discovery.md` (*D200 §n*) and
`JIRA/EPIC-ReliabilityGate-100/COGNIREPO-100-Discovery.md` (*D100 §n*).
**Depends on:** Phase 0 signed off (baseline 2.0.1).

## Context / Why

The user's two named focus areas. The graph is structurally sound (bounded subgraph verified,
D100 §1a) but has no integrity visibility (`stats()` returns only counts,
`knowledge_graph.py:358-363`) and lacks the three roadmapped enrichments (similarity edges — not
implemented, grep-verified D200 §1; Go call completion — partial, `ast_indexer.py:415`;
dynamic-dispatch detection — absent). Episodic memory works but is not yet "the backbone that
keeps track of everything": the record is split across three stores with no merged timeline or
rollup (D200 §3), rotated history becomes unsearchable (archive unread by any consumer, D200 §3),
and decisions rely on agents remembering to call `record_decision`. Phase 2's insights report
reads from what this phase builds — the timeline API here is designed as its data foundation.

## Scope

**In:** graph integrity metrics + doctor wiring; similarity edges; Go call-graph completion +
DYNAMIC_DISPATCH annotation; unified timeline query; episodic robustness (archive search,
embedding cache); decision-coverage improvements.
**Out:** any UI/HTML (Phase 2); mood signals (Phase 3); episodic ID fix (already D02 in
Phase 0).

## Acceptance criteria (epic)

1. `graph_stats` reports orphan-node count, dangling-file-attr count, and last-integrity-sweep
   time; `cognirepo doctor` flags nonzero orphans with a repair suggestion.
2. Semantically related symbols across files are connected by SIMILAR_TO edges (embedding cosine
   ≥ threshold), capped per node, rebuilt by `index-repo`, and visible in `subgraph`.
3. On a Go fixture, `who_calls` resolves ≥90% of a hand-verified caller list; Ansible/Celery
   style registry patterns produce DYNAMIC_DISPATCH-annotated nodes.
4. One call returns a merged, chronologically ordered timeline (sessions + episodes + decisions +
   errors) with a human-readable rollup section; archived events are included on request.
5. Existing behavior unchanged for all current tools (full suite green).

## Stories

### COGNIREPO-201 — Graph integrity sweep + metrics
- **Context/Why:** D100 §3/§4 orphan mechanics; D200 §1 (no integrity metrics).
- **Files:** `data/graph/knowledge_graph.py` (new `integrity_report()`: orphans = non-CONCEPT
  nodes with degree 0; dangling = nodes whose `file` attr no longer exists on disk),
  `interface/server/mcp_server.py` (`graph_stats` tool output extension), doctor check in
  `interface/cli/main.py`, optional `cognirepo graph repair` CLI.
- **Interface contract:** `graph_stats` (existing tool, no schema change — output dict gains
  `integrity: {orphans, dangling_files, swept_at}`; input unchanged → zero manifest-token
  growth).
- **Data flow:** `graph_stats` tool → `KnowledgeGraph.integrity_report()` (graph-owned; tools
  still don't traverse the graph themselves). Repair path: CLI → `remove_file_nodes` for
  danglers.
- **State/schema:** none persisted (sweep is computed); optional cached `swept_at` in graph
  attrs. Back-compat: additive output keys.
- **Dependencies:** COGNIREPO-103 (quarantine) merged.
- **Test oracle:** AC1 — fixture: index, delete a source file bypassing the watcher, sweep →
  dangling count > 0; doctor output contains the warning line.

### COGNIREPO-202 — Similarity edges (SIMILAR_TO)
- **Context/Why:** README.md:634 roadmap item; not implemented (D200 §1). Improves
  `subgraph`/`context_pack` graph scoring for conceptually-related-but-not-calling code.
- **Files:** `intelligence/indexer/ast_indexer.py` (post-index pass: for each symbol vector,
  FAISS k-NN over the AST index; add edge when cosine ≥ 0.80, cap 5/node),
  `data/graph/knowledge_graph.py` (`EdgeType.SIMILAR_TO`), `docs/architecture/graph.md`
  (re-add the type [1.1.3] removed as undocumented-in-code — CHANGELOG.md:69).
- **Interface contract:** no tool changes; edges surface through existing `subgraph`/
  `dependency_graph` outputs.
- **Data flow:** `index-repo` → indexer builds vectors (existing) → new similarity pass →
  `graph.add_edge(sym_a, sym_b, SIMILAR_TO, weight=cosine)` → `graph.save()`. Retrieval reads
  stay inside `hybrid.py` `_graph_score` (`hybrid.py:346`), which can weight SIMILAR_TO.
- **State/schema:** new edge `rel` value in graph.pkl — back-compat safe (readers ignore unknown
  rels); document in graph.md. Index-time cost: one k-NN per symbol — measure on `medium` repo,
  gate behind `indexing.similarity_edges: true` (default on for < 20k symbols).
- **Dependencies:** 201 (so the sweep can count the new edges sanely).
- **Test oracle:** AC2 — two fixture functions with near-identical docstrings/bodies in
  different files get a SIMILAR_TO edge; `subgraph(entity)` includes the counterpart.

### COGNIREPO-203 — Go call-graph completion + dynamic-dispatch annotation
- **Context/Why:** README.md:613-615 (highest-impact unblocked item, per its own words) and
  README.md:626 plugin-registry plan; current state: generic `call_expression` only
  (`ast_indexer.py:415`), no DYNAMIC_DISPATCH (D200 §1).
- **Files:** `intelligence/indexer/ast_indexer.py` (Go selector-expression /
  method-value call extraction), `intelligence/indexer/language_registry.py` +
  `interface/cli/service_detect.py::_SERVICE_MARKERS` (keep in sync — CLAUDE.md rule),
  heuristic pass for `entry_points`/`register`/`__init_subclass__` → node attr
  `dispatch: "dynamic"` + CONCEPT link, tests in `tests/test_indexer_multilang.py`.
- **Interface contract:** no tool changes; `who_calls` coverage improves (it already emits a
  `coverage_note` per QA memory — keep).
- **Data flow:** index-repo → tree-sitter go grammar (loaded already) → new extraction rules →
  CALLS/CALLED_BY edges as for Python.
- **State/schema:** node attr `dispatch` (additive); no migration.
- **Dependencies:** none within epic (parallel to 202).
- **Test oracle:** AC3 — Go fixture in `cognirepo_test_repo/advanced` (verify Go files exist
  there first; else add a small fixture under `tests/fixtures/`) with a hand-listed caller set;
  who_calls hit-rate ≥ 90%; a Celery-style `@app.task` fixture yields `dispatch: "dynamic"`.

### COGNIREPO-204 — Unified timeline: `get_timeline` data API + rollup
- **Context/Why:** D200 §3 — three stores, no merged view, no rollup; foundation for Phase 2
  insights.
- **Files:** new `data/memory/timeline.py` (merge logic — data layer owns cross-store reads of
  its own stores), `interface/tools/` thin assembly, `interface/server/mcp_server.py`
  registration, `docs/MCP_TOOLS.md`.
- **Interface contract (new MCP tool):**
  `get_timeline(since: str = "7d", include_archived: bool = False, limit: int = 100,
  repo_path: str | None = None) -> dict` returning
  `{status, window, entries: [{ts, kind: "session"|"episode"|"decision"|"error"|"index_event",
  summary, ref}], rollup: str}` — `rollup` is a deterministic template summary (counts + top
  items), NOT model-generated. Manifest cost: ~140 tokens (comparable to `record_decision`,
  145 — D100 §2). Justification (Ground Rule 3): replaces 3 required calls
  (`get_session_history` + `episodic_search` + `get_error_patterns`) for "what happened"
  queries — net token reduction; also consider folding a 5-entry digest into
  `get_agent_bootstrap` output (zero-token option) — final call at implementation, both designs
  acceptable, digest-in-bootstrap preferred if timeline fits.
- **Data flow:** tool → `timeline.merge(since)` → reads episodic (`get_history` +
  archive file when `include_archived`), sessions dir (same parse as
  `mcp_server.py:1697-1746` — extract that parser into the data layer to avoid duplication),
  behaviour error patterns → sort by ISO ts → rollup template.
- **State/schema:** none new; read-only over existing stores.
- **Dependencies:** D02 fixed (unique IDs make `ref` stable).
- **Test oracle:** AC4 — fixture with 2 sessions + 3 episodes + 1 decision + 1 error → one call
  returns 7 ordered entries and a rollup mentioning the decision; `include_archived=True` pulls
  rotated events.

### COGNIREPO-205 — Episodic robustness: archive search + embedding cache + decision coverage
- **Context/Why:** D200 §2/§3 — archive unread by search; `_semantic_episode_search` re-embeds
  the corpus per query (`episodic_memory.py:179-192`); decision logging is best-effort only.
- **Files:** `data/memory/episodic_memory.py` (optional `include_archived` param on
  `search_episodes`; persistent embedding cache keyed by entry id under
  `.cognirepo/memory/episodic_vecs.npy` or reuse of the semantic vector store),
  `interface/server/mcp_server.py` (`episodic_search` passthrough param — additive),
  auto-episode hooks: `index-repo` completion and `org rewire` log an episode (they currently
  don't) so the timeline has system events.
- **Interface contract:** `episodic_search` gains optional `include_archived: bool = False`
  (+~15 manifest tokens).
- **Data flow:** unchanged path; cache read inside data layer.
- **State/schema:** new cache file under `.cognirepo/memory/` — regenerable, safe to delete;
  document in CONFIGURATION.md storage layout.
- **Dependencies:** D02 (IDs are cache keys).
- **Test oracle:** archived event found with flag on, not without; second identical semantic
  search performs zero encode calls (assert via monkeypatched counter).

## Architecture-rule compliance

Retrieval additions stay inside `intelligence/retrieval/hybrid.py` (202's scoring) and the data
layer (204/205 merges) — tools remain thin and stateless. One new MCP tool (204) with explicit
token justification, or the zero-token bootstrap-digest variant. No storage outside
`.cognirepo/`. No CLAUDE.md amendment needed; CLAUDE.md tool-routing table gains a `get_timeline`
row when it ships.

## Version bump

**2.1.0** (from 2.0.1) — additive: new edge type, new/extended tool outputs, new optional params.
No breaking changes.

## Risks / open questions

- Similarity-edge threshold/cap (0.80 / 5) are unvalidated guesses — tune on the `medium` test
  repo; risk of CONCEPT-noise echoing the builtin-noise problem `PYTHON_BUILTINS` solved
  (`knowledge_graph.py:31-66`).
- Index-time cost of 202 on 2M-LOC repos unknown — config gate is the mitigation.
- 204's tool-vs-bootstrap-digest choice needs a token measurement at implementation time; the
  story's oracle covers both.
- Whether `cognirepo_test_repo/advanced` contains Go sources must be checked before writing
  203's test suite (its TEST_SUITE marks this BLOCKED-until-verified).
