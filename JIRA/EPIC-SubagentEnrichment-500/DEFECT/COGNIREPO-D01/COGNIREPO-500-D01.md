# COGNIREPO-500-D01 — independence grouping over-fragments on large (weight-filtered) repos

Epic: COGNIREPO-500 · Branch: defect/COGNIREPO-500-D01 · Base: development
Found while manually testing: COGNIREPO-502 (TC-502-1)
Does NOT block COGNIREPO-501 or COGNIREPO-502's own acceptance criteria — both pass as written.
Blocks: epic COGNIREPO-500 sign-off (per skill.md §G.4) until resolved or explicitly deferred.

## Backstory

`intelligence/indexer/ast_indexer.py:1818-1826` gates full graph population (proper
`type`/`file` node attrs + a `DEFINED_IN` symbol→FILE edge) behind
`weight >= getattr(self, "_graph_weight_min", 0.0)` — a deliberate OOM guard for large repos
(comment: "skipped or weight-filtered for large repos to prevent OOM"). Symbols below that
weight still get referenced as call-graph edge endpoints elsewhere (`CALLS`/`CALLED_BY`), and
`networkx` auto-creates the node on `add_edge()` with **zero attributes** when it doesn't
already exist.

`intelligence/retrieval/hybrid.py::_reachable_files()` (COGNIREPO-501) relies entirely on those
attrs — `_record()` checks `data.get("type") == NodeType.FILE` or `data.get("file")` — to map a
symbol back to its file. A node with no attrs contributes nothing to its own reachable-file set,
and (since the `DEFINED_IN` edge was never written either) never connects to its own FILE node
through that path either.

## Repro (measured, not estimated)

```
cognirepo_test_repo/advanced/moby         77,772 nodes — 60,220 (77.4%) have zero attrs
cognirepo_test_repo/advanced/kubernetes   76,784 nodes — 61,941 (80.7%) have zero attrs
cognirepo_test_repo/easy/flask (Python)    1,945 nodes —      0 ( 0.0%) have zero attrs
```

Two functions confirmed in the **same file** in moby —
`daemon/container.go::GetContainer` and `daemon/container.go::load` — were fed through the real
(unmocked) `HybridRetriever._annotate_independence_groups()` and got **different**
`component_id`s (`g0`/`g1`), when a same-file pair should always land in one group (same-file
symbols share a `DEFINED_IN` edge to the same FILE node, which is exactly the case that's
missing here). Confirmed via direct node inspection: both nodes' attrs are `{}`, and neither has
a `DEFINED_IN` edge in either direction — only `CALLS`/`CALLED_BY` edges to other symbols, many
of which are themselves attr-less stubs.

Reproduce:
```python
# cwd = cognirepo_test_repo/advanced/moby (already indexed)
from data.graph.knowledge_graph import KnowledgeGraph
kg = KnowledgeGraph()
n = "daemon/container.go::GetContainer"
print(dict(kg.G.nodes[n]))                 # {}  <- should have type/file/line/weight
print(list(kg.G.predecessors(n)))          # no DEFINED_IN edge to daemon/container.go
```

## Description

Not a crash and not a ranking-safety issue — `_annotate_independence_groups` still returns
byte-identical scores/order/status per COGNIREPO-501 AC2, it just over-fragments: on a large
repo, most hits will get distinct `component_id`s regardless of real structural connectivity,
because the signal `_reachable_files` depends on (node attrs + `DEFINED_IN` edges) was
deliberately never written for the majority of nodes. This degrades COGNIREPO-501's grouping
*and* COGNIREPO-502's `delegation_hints` (more spurious "independent" groups than are real) on
exactly the class of repo (large, real-world) both stories were dogfooded against — 501's own
manual test happened to use `ansible` (17.6k nodes), which is small enough that its `_graph_min`
filter apparently doesn't trim much; it never exercised the filtered-majority case.

**This needs an owner decision, not a unilateral fix** — the weight filter exists specifically
to bound memory on large repos, and lifting it wholesale could reintroduce the OOM risk it was
added for. Options, roughly cheapest-to-most-invasive:

1. When a node is auto-created as a call-graph edge endpoint below `_graph_min`, still stamp
   minimal `type`/`file` attrs (no embedding, no FAISS write — just a few dict keys) so
   `_reachable_files` can use it. Cheapest; needs verifying this doesn't reintroduce the
   original OOM pressure (the costly part was presumably embedding/FAISS writes, not attrs).
2. Have `_record()` fall back to parsing the file path out of the node ID itself
   (`"daemon/container.go::GetContainer"` → `"daemon/container.go"`) when attrs are missing,
   since the ID format is already deterministic (`graph_utils.make_node_id`). Zero indexer
   changes, but `.file` extraction. by string-split is a bit implicit relying on ID format.
3. Leave as-is and document the limitation (grouping is best-effort/degrades on repos above
   some node-count threshold) — cheapest of all, but means `delegation_hints` quietly gets less
   useful exactly on the repos where subagent delegation would help most.

## Acceptance criteria

1. Reproduce the same-file test above post-fix: two symbols confirmed in the same file get the
   same `component_id` on `cognirepo_test_repo/advanced/moby` (or a chosen fix's equivalent
   evidence, if option 3/documentation-only is chosen instead).
2. No regression to COGNIREPO-501 AC2 (byte-identical scores/order with grouping disabled) or
   AC4 (<10ms latency budget) — re-run `tests/test_hybrid_retrieval.py`.
3. No measurable regression in indexing memory/time on `moby`/`kubernetes` if option 1 is taken
   (re-run indexing, compare peak RSS before/after).

## Risks / notes

- This is a design tradeoff (memory vs. grouping accuracy), not a straightforward bug fix —
  flagging for the user to pick a direction before implementation starts.

## Addendum (2026-08-30) — related cache-keying issue found while CI-debugging this ticket

`_grouping_allowed()`'s `_integrity_gate_cache` (`intelligence/retrieval/hybrid.py`) is a
single module-level dict shared by every caller in the process, with no key on which repo/graph
it was computed for. `HybridRetriever.__init__` constructs a fresh `KnowledgeGraph()` per call,
and `_repo_ctx()` (mcp_server.py) repoints storage at a different repo's `.cognirepo/` for
cross-repo tool calls within the SAME long-lived MCP server process — so a cross-repo call can
read (and serve, for up to the 300s TTL) an integrity-gate verdict that was actually computed
against a *different* repo's graph. Confirmed as a real race (not just a test artifact) while
fixing CI flakiness in `test_grouping_allowed_trips_on_high_orphan_count`
(COGNIREPO-502/PR #64): the shared cache dict was observably repopulated by a concurrent
caller between one test forcing a fresh check and that same test's own `_grouping_allowed()`
call — the test-side fix was isolating the test onto a private dict via `monkeypatch.setattr`,
but production code has no equivalent isolation. Likely fix: key the cache by `repo_root` (or
`id(graph)`/a hash of the graph's disk path) instead of one flat dict. Not fixed here — flagging
alongside the primary D01 finding since both concern this same integrity-gate mechanism, but
this is a separate, more clear-cut correctness bug (no design tradeoff needed) rather than the
above's memory-vs-accuracy call.
