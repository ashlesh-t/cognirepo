# COGNIREPO-D09 — BehaviourTracker.save() is a last-write-wins race under concurrent MCP calls

Epic: COGNIREPO-100 · Branch: story/COGNIREPO-105 · Base: development

## Backstory
Found while re-verifying TC-D04-1 / TC-105-1 live against the `cognirepo-ansible` MCP server
after the COGNIREPO-D04/D05/D06/D07/D08 fixes landed. `summarize_interaction_style()` itself
worked correctly in an isolated call (`store_fn` invoked, `last_summarized` set,
`query_patterns` cleared, memory retrievable with `source="interaction_style"`), but the
*live* server never reached that state: `query_patterns` stayed pinned at its 50-entry ring
buffer cap and `last_summarized` stayed `null` indefinitely, even after 50+ real queries.

Root cause: `interface/server/mcp_server.py::_behaviour_record_query()` constructs a brand
new `BehaviourTracker(g, db_adapter=..., store_fn=_store_memory)` on *every* `retrieve_memory`
call — load, mutate, save, with no synchronization. `BehaviourTracker.save()`
(`data/graph/behaviour_tracker.py`, pre-fix) did a plain read-modify-write: serialize
`self.data` and overwrite `behaviour.json` unconditionally. When an agent issues several
`retrieve_memory` calls in parallel (a normal pattern for MCP-driven clients batching
independent lookups), each request's tracker loads the *same* on-disk snapshot, and whichever
request's `save()` runs last wins outright — silently discarding any `query_history` entries,
`symbol_weights`, or (critically) the `query_patterns` reset + `last_summarized` timestamp
that a concurrent request's `summarize_interaction_style()` had just written.

This reproduces reliably: fire ~10 `retrieve_memory` calls in one parallel batch → inspect
`.cognirepo/graph/behaviour.json` → `interaction_style.last_summarized` is `null` and
`query_patterns` length is stuck at 50, despite `query_history` (a monotonic counter) growing
normally. Re-running the same queries **sequentially** (no concurrency) works every time.

## Description
`BehaviourTracker.save()` now acquires a dedicated file lock (`_behaviour_lock()`, scoped to
`behaviour.json` only — deliberately *not* `core.config.lock.store_lock()`, to avoid nesting
with the vector-DB write lock that `store_fn` acquires downstream during
`summarize_interaction_style()`) and, while holding it, re-reads the current on-disk state and
additively merges it into `self.data` before writing (`_merge_from_disk()`), mirroring the
existing `OrgGraph.save()` compose-on-save pattern in `data/graph/org_graph.py`:

- `query_history`: union by key (each query has a fresh uuid — always additive, no conflicts).
- `symbol_weights`: keep the higher `hit_count` per symbol between disk and memory.
- `interaction_style`: if disk's `last_summarized` differs from what this instance loaded,
  another writer already summarized and reset the ring buffer since — adopt disk's
  post-summarize state wholesale and replay only the query text(s) *this* instance appended
  since its own load, so they aren't lost either.

`_load()` now records `self._loaded_query_patterns` / `self._loaded_last_summarized` snapshots
at construction time so `_merge_from_disk()` can tell "my own new queries" apart from "someone
else's newer reset".

## Acceptance criteria
1. Two `BehaviourTracker` instances loaded from the same on-disk state, each recording a
   different query and calling `save()` in sequence, must both have their `query_history`
   entries present afterward (neither is dropped).
2. If instance A crosses the summarize threshold and saves first (setting
   `last_summarized` + clearing `query_patterns`), instance B's later `save()` must not revert
   `last_summarized` to `null` or restore the pre-summarize `query_patterns`; B's own new query
   must still appear (replayed onto the post-summarize buffer).
3. `retrieve_memory('interaction style')` against a live server, after driving the query count
   past `_STYLE_SUMMARIZE_EVERY` **in parallel**, returns a `source="interaction_style"` memory
   (previously required sequential queries to work around this defect).
4. Existing test suite green.

## Risks / notes
- Pre-existing bug, not introduced by COGNIREPO-105 or the D04–D08 fixes — those fixes made
  `summarize_interaction_style()` itself correct, which is what exposed this as the next
  blocker in the same code path.
- The merge logic is intentionally conservative (union / max / adopt-newer-summary) rather
  than a generic deep merge; it only resolves the fields this defect actually touches. A
  broader concurrent-write audit of `BehaviourTracker` (session_registry, error_patterns,
  user_preferences, query_rewrites) is out of scope here.
