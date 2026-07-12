# Phase 4 — Sub-agent delegation as data enrichment → v2.4.0

**Epic:** COGNIREPO-500 (`JIRA/EPIC-SubagentEnrichment-500/`). Evidence:
`JIRA/EPIC-SubagentEnrichment-500/COGNIREPO-500-Discovery.md` (*D500 §n*).
**Depends on:** Phase 1 (graph integrity — independence math needs a trustworthy graph).

## Context / Why

CogniRepo is a memory/retrieval layer, not an orchestrator: `interface/tools/` is stateless
(CLAUDE.md), and no spawning machinery exists (D500 §1 — scope agreement, no dissent). What it
*can* do is tell a consuming Claude Code session which parts of the retrieved context are
structurally independent — no path between their files through
IMPORTS/CALLS/DEFINED_IN edges (`knowledge_graph.py:267-281` `hop_distance`/`shortest_path`) —
so the session can decide to delegate. This is data enrichment of `context_pack`'s existing
output (`context_pack.py:218-231` contract), not execution.

## Scope

**In:** independence grouping of context_pack hits; opportunistic TODO/FIXME surfacing within
hit files; `delegation_hints` output block; consumer guidance in CLAUDE.md.
**Out:** spawning/queueing/agent lifecycle anything; repo-wide TODO inventory (only hit files);
new MCP tools.

## Acceptance criteria (epic)

1. When a `context_pack` result contains hits from ≥2 graph-disconnected file groups, the output
   includes `delegation_hints: [{group: int, files: [...], reason: "no shared
   import/call path"}]`; when all hits are connected, the key is **absent** (no fixed token
   cost).
2. TODO/FIXME lines inside returned hit files are listed per group (max 3/group,
   `{file, line, text}`).
3. Added output ≤ ~60 tokens for the two-group case; zero when absent (measured with the same
   tiktoken counter, `context_pack.py:56-57`).
4. CLAUDE.md documents how a session should consume the hints.
5. Retrieval results (hits, scores, status) are byte-identical with the feature's grouping
   removed — enrichment never changes ranking.

## Stories

### COGNIREPO-501 — Independence grouping in hybrid retrieval
- **Context/Why:** D500 §3 — grouping belongs where graph scoring already lives
  (`hybrid.py:346-403` `_graph_score`), keeping tools out of the graph (Ground Rule 2).
- **Files:** `intelligence/retrieval/hybrid.py` (post-score pass: union-find over hit files
  using graph connectivity restricted to IMPORTS/CALLS/CALLED_BY/DEFINED_IN edges with a hop cap
  ~3; emit `component_id` per hit), tests in `tests/test_hybrid_retrieval.py`.
- **Interface contract:** internal — `hybrid_retrieve` result dicts gain `component_id`.
  No MCP schema change.
- **Data flow:** query → `hybrid_retrieve` (`hybrid.py:440`) → merge/score (existing) → new
  connectivity pass (graph read APIs) → annotated candidates.
- **State/schema:** none.
- **Dependencies:** COGNIREPO-201 (orphan-free graph — disconnected-by-corruption must not
  masquerade as parallelizable; the pass checks `integrity_report()` and skips grouping when
  orphan count is high, emitting no hints).
- **Test oracle:** AC5 (golden comparison of hits with/without) + unit: two fixture files with
  no shared edges → distinct `component_id`; add an IMPORTS edge → same id.

### COGNIREPO-502 — `delegation_hints` surface + TODO scan + consumer docs
- **Context/Why:** D500 §2/§4/§5.
- **Files:** `interface/tools/context_pack.py` (assemble hints from `component_id`s;
  pack-time grep for `TODO|FIXME` over hit files only — D500 §2, no index change),
  `docs/MCP_TOOLS.md` (context_pack section), `CLAUDE.md` routing table line, tests in
  `tests/test_context_pack.py`.
- **Interface contract:** `context_pack` **output** gains the conditional `delegation_hints`
  key (AC1 shape). Input schema unchanged → manifest tokens +0. (The MCP_TOOLS.md doc grows;
  the schema does not.)
- **Data flow:** tool → hybrid results (with `component_id`) → group → grep hit files →
  hints block appended inside the existing `max_tokens` budget (hints are counted against the
  budget last and dropped first on overflow — core content always wins).
- **State/schema:** none.
- **Dependencies:** 501.
- **Test oracle:** AC1/AC2/AC3 — fixture with two unrelated modules each containing a TODO:
  one call yields 2 groups, ≤3 TODOs each, measured token delta ≤ 60; connected fixture → key
  absent.

## Architecture-rule compliance

Fully compliant: no new tools (0 manifest tokens), graph access stays behind
`intelligence/retrieval/hybrid.py`, `interface/tools/` stays stateless, no storage changes, no
orchestration. CLAUDE.md change is guidance, not a rule amendment.

## Version bump

**2.4.0** (from 2.3.0) — additive output enrichment on the flagship tool.

## Risks / open questions

- False "independent" signals from a sparse/immature graph (fresh repos, non-Python) could
  prompt bad delegation — mitigated by the 501 integrity gate and by `reason` strings letting
  the consumer judge; flagged as the epic's main quality risk.
- Hop-cap (3) and TODO cap (3/group) are initial guesses; tune on `medium`/`advanced` test
  repos.
- Honest-scope note (per the brief's invitation to disagree): none — the enrichment scope is
  the right one for this codebase; an execution layer would violate its architecture and add
  the exact overhead Ground Rule 3 warns about.
