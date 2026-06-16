# Follow-Up Items — deferred from v1.2.3 audit

These items were found during the v1.2.3 production-readiness audit but require
behaviour changes or significant refactoring beyond the scope of a patch release.

---

## 1. Architecture-rule compliance gap in `server/mcp_server.py`

**Finding:** Several `@mcp.tool()` functions in `server/mcp_server.py` instantiate
`KnowledgeGraph()` and `ASTIndexer()` directly (e.g. lines 246, 397, 865, 1285) rather
than routing through a `tools/` function. The architectural rule states: "If you are
writing logic in `server/mcp_server.py` — stop. Move it to a function in `tools/`."

**Why deferred:** Moving these would require creating new `tools/` functions and
updating all call sites — non-trivial blast radius for a patch release. The existing
tests continue to pass; this is a structural drift, not a functional bug.

**Recommended action:** Audit every `@mcp.tool()` function that does more than
`return tools.X.y(...)`. For each, extract the logic into a named function in the
relevant `tools/` module and reduce the MCP handler to a one-liner dispatch.

---

## 2. `SIMILAR_TO` edge type documented but never defined

**Finding:** `docs/architecture/graph.md` previously documented `EdgeType.SIMILAR_TO`
(removed in v1.2.3 patch), but the constant was never present in `graph/knowledge_graph.py`.
The sync test (`test_edge_types_match_docs`) only checks code → docs direction, not
docs → code. No code actually emits `SIMILAR_TO` edges.

**Recommended action:** Either implement `SIMILAR_TO` (wire it in `indexer/ast_indexer.py`
based on embedding-distance similarity between symbols) or formally document the
decision not to implement it. The sync test should also be extended to check the
reverse direction (every edge type in `graph.md` must exist in `EdgeType`).

---

## 3. `_build_manifest()` in `server/mcp_server.py` lists 32 tools; `@mcp.tool()` registers 34

**Finding:** `find_symbol_path` and `get_service_endpoints` are registered via `@mcp.tool()`
and included in `_REGISTERED_TOOLS`, but are absent from the `list_tools` manifest dict
built by `_build_manifest()`. FastMCP will serve them (the decorator is authoritative),
but the JSON manifest written to `server/manifest.json` is incomplete.

**Recommended action:** Add `find_symbol_path` and `get_service_endpoints` entries to the
`_build_manifest()` tool list so the JSON manifest matches actual served tools. Low risk,
but touching that 2600-line function warrants a dedicated PR with focused testing.

---

## 4. CHANGELOG.md historical formatting drift

**Finding:** `[1.1.0]` has two `### Added` sections and two `### Fixed` sections within the
same version block (one set labelled "release-readiness pass, 2026-06", one not). `[1.0.0]`
has a non-standard `### Also in 1.0.0` section.

**Why deferred:** Ground Rule #2 says don't rewrite history; `[1.2.3]` and all future
entries use correct single-section format.

**Recommended action:** On the next major version bump, squash the `[1.1.0]` duplicate
sections into one coherent block to reduce future confusion.

---

## 5. `docs/METRICS.md` benchmark numbers not re-validated

**Finding:** `docs/METRICS.md` carries specific latency, token-reduction, and precision@k
numbers from live sessions. The benchmark scripts (`cognirepo benchmark`,
`tests/test_benchmark_metrics.py`) could not be re-run against the same external repos used
in the original measurements (network/fixture constraints in this audit pass).

**Recommended action:** Schedule a periodic benchmark run (e.g. quarterly, in CI against a
pinned fixture repo) and update `docs/METRICS.md` with the date and environment. Numbers
currently carry the note `(last verified: inferable from git history, not re-run in v1.2.3 pass)`.

