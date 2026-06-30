# IMPROVEMENTS.md

Deferred improvements identified during the v1.2.0 depth-oriented restructure.
These are not bugs — the codebase works correctly — but represent technical debt
worth addressing in a future cycle.

---

## 1. `data.graph.behaviour_tracker` → `interface.tools.store_memory` (upward callback)

**File:** `data/graph/behaviour_tracker.py` (lazy import at line ~540)

**Issue:** `BehaviourTracker.auto_summarize()` does a lazy import of
`interface.tools.store_memory` to persist summarized interaction style. This is
a `data → interface` upward call in the dependency graph. It is currently safe
because the import is lazy (inside a function body), but it violates the layer
invariant.

**Suggested fix:** Extract the auto-store callback as an injectable dependency
(pass a `store_fn: Callable[[str], None] | None = None` parameter to
`BehaviourTracker.__init__`). The caller at the interface layer supplies the
real store function; in unit tests, pass `None` or a mock. This eliminates the
upward dep without changing behavior.

---

## 2. Four MCP tools missing from `_build_manifest()` (server/manifest.json)

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

## 3. Shim packages scheduled for removal in v2.0

The following backward-compat shim packages at the repo root emit
`DeprecationWarning` and will be **removed in v2.0**:

| Shim (old path) | New path |
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
