# COGNIREPO-D10 — Orphan CONCEPT stub survives symbol deletion; total_symbols drifts

Epic: COGNIREPO-100 · Branch: defect/COGNIREPO-D10_D11_D12 · Base: development

## Backstory
Found running `E2E-100-1` (`JIRA/EPIC-ReliabilityGate-100/COGNIREPO-100-TEST_SUITE.md`) live
against a watcher-indexed repo: a function (`count_terms`) was deleted from a source file and
saved. `lookup_symbol("count_terms")` correctly returned empty, but `subgraph("count_terms")`
still showed a live `symbol::count_terms` CONCEPT node with 4 CALLS + 4 CALLED_BY edges to its
callers (`check_mutually_exclusive`, `check_required_one_of`, `check_required_together`,
`check_required_if`). This is the exact class of bug COGNIREPO-103 ("orphan-node cleanup on
re-index") was meant to fix — but COGNIREPO-103's own test
(`tests/test_stale_cleanup.py:260-302`,
`TestFileWatcherReindexOrphanCleanup::test_removed_function_leaves_no_orphan_node`) mocks
`indexer.index_file` entirely, so it never exercises real call-edge/stub creation and missed
this.

Root cause, traced to `intelligence/indexer/ast_indexer.py`:
- `index_file()` (`:1622-1631`) creates an unconditional `symbol::{callee_name}` CONCEPT stub
  node for every call edge, regardless of whether a real definition for that callee exists.
- `_resolve_call_stubs()` (`:1708-1756`) is the *only* code that merges a stub into its real
  `{file}::{name}` node (when exactly one definition exists elsewhere); it is called *only*
  from the full-reindex path `index_repo()` (`:1428-1436`) — **never** from the watcher's
  incremental batch handler `flush()` (`intelligence/indexer/file_watcher.py:160-186`).
- `KnowledgeGraph.remove_file_nodes()` (`data/graph/knowledge_graph.py:213-232`) only removes
  nodes with a matching `file` attribute — stubs never carry one, so they're structurally
  invisible to this cleanup regardless of when it runs.

Net effect: in a repo indexed purely via watcher saves (no full `cognirepo index-repo` run),
every call edge creates a permanent duplicate `symbol::name` stub alongside the real definition
node, and it is never merged/pruned incrementally. When the real symbol is later deleted, only
the real node disappears; the stub — with its live CALLS/CALLED_BY edges from other callers —
survives forever.

**Bonus defect, same root cause:** `save()` (`ast_indexer.py:2107`) writes the manifest's
`symbol_count` from the cached `index_data["total_symbols"]`. The full-reindex path recomputes
this before `save()` (`:1983-1984`); the watcher's `flush()` never does, so after any
incremental add/delete the manifest's symbol count silently drifts from the live FAISS/AST
count (observed live: FAISS 17,342 vs manifest 17,343).

## Description
1. Give `_resolve_call_stubs()` an optional `names: set[str] | None` parameter — when
   provided, restrict the stub scan to `symbol::{n}` for `n in names` instead of every stub
   node in the graph. The existing no-arg full-sweep call in `index_repo()` is unchanged.
2. Before a real symbol node with incoming CALLED_BY predecessors is removed (in
   `remove_file_nodes()` or at its `file_watcher.py` call sites), redirect those edges onto a
   (re-)created `symbol::{name}` CONCEPT stub tagged `unresolved=True`, reusing the existing
   "unresolved stub kept for `who_calls` visibility" convention instead of a new data shape.
3. In `flush()` (`file_watcher.py:160-186`): collect the union of symbol names touched by the
   whole batch (added and removed), call `self.indexer._resolve_call_stubs(names=touched)`
   after `_build_reverse_index()`, and add the missing `total_symbols` recompute (mirroring
   `ast_indexer.py:1983-1984`) right before `self.indexer.save()`.

## Acceptance criteria
1. Indexing file A (which calls a function defined in file B) via the watcher path, then
   indexing file B, resolves the `symbol::fn` stub into the real `B::fn` node (scoped
   resolution runs after every batch, not just full reindex).
2. Deleting file B's function via the watcher path leaves **no** node with live
   CALLS/CALLED_BY edges for the deleted symbol — `subgraph()` on the deleted name returns
   nothing live, matching `lookup_symbol()`'s already-correct empty result.
3. After any incremental watcher add/delete, the manifest's `symbol_count` matches the live
   FAISS/AST-index symbol count (no drift).
4. Existing test suite green; `tests/test_stale_cleanup.py` gains a real (unmocked)
   `index_file` test exercising this exact scenario (cross-file call edge → deletion).

## Risks / notes
- Fix first among D10/D11/D12 — highest severity, since it's live graph-data corruption, not
  just a missing warning.
- Scoped `_resolve_call_stubs(names=...)` keeps the per-save cost proportional to the batch
  size, not the whole graph — important since `flush()` runs on every debounced save.
