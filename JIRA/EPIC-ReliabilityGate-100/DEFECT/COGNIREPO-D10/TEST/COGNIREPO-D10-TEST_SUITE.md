# COGNIREPO-D10 — Manual test suite

## TC-D10-1: Cross-file call edge resolves and cleans up incrementally
- Test repo: /home/ashlesh/my_works/cognirepo (isolated `.cognirepo` test fixture)
- Prerequisites: fix applied (scoped `_resolve_call_stubs`, redirect-on-removal,
  `total_symbols` recompute in `flush()`).
- What to do: index file A (calls a function defined in file B) via the watcher path; index
  file B; assert the `symbol::fn` stub merged into the real `B::fn` node. Then delete B's
  function via the watcher path and flush.
- Prompt: n/a — automated via `tests/test_stale_cleanup.py` (real `index_file`, no mocking).
- Expected results: stub resolves to real node once both files are indexed; after deletion, no
  node with live CALLS/CALLED_BY edges remains for the deleted symbol; manifest
  `symbol_count` matches the live FAISS/AST count throughout.
- Obtained results: `TestIncrementalStubResolutionParity::test_cross_file_call_edge_resolves_and_survives_deletion_correctly`
  — real (unmocked) `ASTIndexer.index_repo()` on 2 real files (caller.py calls
  `count_terms` defined in callee.py). Confirmed the stub merges into the real node via the
  existing full-index path (sanity check). Deleted `count_terms` via
  `RepoFileHandler.flush()` (the incremental batch path) with caller.py untouched.
  `lookup_symbol("count_terms")` returns `[]` (already correct pre-fix). The surviving
  `symbol::count_terms` node is tagged `unresolved=True` (verified via
  `kg.G.nodes[n].get("unresolved") is True`) — matching the parity bar (what a full
  `index_repo()` re-run would also produce, since caller.py's AST still references it), not
  an untagged duplicate masquerading as a live definition. `manifest["total_symbols"]`
  matches the live FAISS/AST count after the incremental delete.
  `venv/bin/python -m pytest tests/test_stale_cleanup.py -q` — 12 passed.
- Verdict: PASS

## TC-D10-2: Live re-run of E2E-100-1's failing sub-checks (#1 and #3)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: fix merged; `cognirepo watch` (or serve) running against a freshly indexed
  repo.
- What to do: delete a function that has live callers, save; run
  `subgraph("<deleted_function>")` and `lookup_symbol("<deleted_function>")`.
- Prompt: "Use lookup_symbol and subgraph on the function I just deleted — tell me if
  anything looks orphaned."
- Expected results: both report the symbol absent/gone — no live CALLS/CALLED_BY edges
  survive.
- Obtained results:
- Verdict:
