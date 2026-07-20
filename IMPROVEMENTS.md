# IMPROVEMENTS.md

Deferred improvements identified during the v1.2.0 depth-oriented restructure.
These are not bugs — the codebase works correctly — but represent technical debt
worth addressing in a future cycle.

---

## 1. `data.graph.behaviour_tracker` → `interface.tools.store_memory` (upward callback)

**RESOLVED by COGNIREPO-105.** `BehaviourTracker.__init__` now takes an optional
keyword-only `store_fn: Callable[..., Any] | None = None`; `summarize_interaction_style()`
calls `self._store_fn(...)` instead of lazily importing `interface.tools.store_memory`,
and returns `False` (no-op) when no callback was injected. All production
construction sites (`interface/cli/main.py`, `interface/cli/seed.py`,
`interface/tools/context_pack.py`, `interface/tools/behaviour_hook.py`,
`interface/server/mcp_server.py`) now wire `store_fn=store_memory`. The unrelated
`start_watching()`/`stop_watching()` methods (which also lazily imported
`intelligence.indexer.ast_indexer`, another upward dep) were deleted as dead code —
zero production callers existed for either. See `scripts/check_circular_deps.py`
(now a hard-failure check on both toplevel and lazy upward imports, not just
toplevel) and `JIRA/EPIC-ReliabilityGate-100/STORY/COGNIREPO-105/`.

A related upward-import finding in `core/vector_db/local_vector_db.py`
(`core → data.memory.circuit_breaker`/`cleanup_queue`) was surfaced by the same
audit but could not be resolved via the same mechanical-DI pattern without a real
behavior regression — deferred to `JIRA/EPIC-ReliabilityGate-100/DEFECT/COGNIREPO-D06/`.

---

## 2. Four MCP tools missing from `_build_manifest()` (server/manifest.json)

**RESOLVED** — see `COGNIREPO-D01`/`COGNIREPO-101`.

**File:** `interface/server/mcp_server.py`

**Issue:** The following tools are registered via `@mcp.tool()` and callable via
MCP but are absent from the `_build_manifest()` dict and therefore missing from
`server/manifest.json` + the `export-spec` command output:

- `find_symbol_path`
- `get_service_endpoints`
- `search_token`
- `get_agent_bootstrap`

**Impact:** Agents that discover tools via the manifest will not know these tools
exist. They only appear if the client calls `tools/list` via the MCP protocol.

**Suggested fix:** Add these four tools to `_build_manifest()` with their
parameter schemas and description strings, then regenerate `server/manifest.json`
by running `cognirepo export-spec`.

---

## 3. Old top-level import paths removed, not shimmed (v2.0.0)

An earlier draft of this restructure planned backward-compat shim packages
at the repo root (`sys.modules` redirects emitting `DeprecationWarning`) for
the old flat-layout import paths below. Those shims were never actually
implemented — the old packages were `git mv`'d away with nothing left in
their place, and `pyproject.toml`'s `packages.find.include` dropped all 14
old names. Rather than build and verify a shim layer after the fact, the
old paths were removed outright and the release was cut as a breaking major
version (`2.0.0`) instead of a minor bump. See `CHANGELOG.md` under
`[2.0.0] BREAKING CHANGES`.

| Old path (removed) | New path |
|---|---|
| `_bm25` | `core._bm25` |
| `config` | `core.config` |
| `security` | `core.security` |
| `vector_db` | `core.vector_db` |
| `memory` | `data.memory` |
| `graph` | `data.graph` |
| `indexer` | `intelligence.indexer` |
| `retrieval` | `intelligence.retrieval` |
| `orchestrator` | `intelligence.orchestrator` |
| `tools` | `interface.tools` |
| `server` | `interface.server` |
| `adapters` | `interface.adapters` |
| `cli` | `interface.cli` |
| `cron` | `ops.cron` |

Any external code still using these old import paths should migrate before v2.0.
