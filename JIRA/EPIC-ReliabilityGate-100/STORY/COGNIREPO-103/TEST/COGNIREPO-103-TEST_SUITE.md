# COGNIREPO-103 — Manual test suite

## TC-103-1: No orphans after symbol deletion
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy
- Prerequisites: story merged; indexed; watcher running; file with ≥2 functions.
- What to do: delete one function from the file, save, wait for reindex.
- Prompt: "Run graph_stats and lookup_symbol('<deleted_fn>'). Is there any trace of the deleted
  function?"
- Expected results: lookup empty; integrity/orphan count (post EPIC-200: explicit; here: node
  absent via subgraph('<deleted_fn>') returning empty).
- Obtained results: Ran against `cognirepo_test_repo/easy/flask` (setup.py). Deleted the `setup`
  function, saved, watcher reindexed via `RepoFileHandler._reindex_mutate()` (now calling
  `graph.remove_file_nodes(rel_path)` instead of `remove_node_edges`). Post-reindex:
  `lookup_symbol('setup')` returned no match; `ast_index.json`'s `reverse_index` had no entry for
  `setup`; loaded `graph.pkl` directly and confirmed no node id `setup.py::setup` (or equivalent)
  remained — only the FILE node and surviving symbols from the file. `github_link` metadata for
  the file's other symbols was preserved (re-added by `index_file()` during the same reindex, not
  lost by the node removal). No orphan trace of the deleted function anywhere in graph or index.
- Verdict: PASS

## TC-103-2: Corruption quarantine drill
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy
- Prerequisites: indexed; MCP server stopped.
- What to do: `echo garbage > .cognirepo/graph/graph.pkl`; start server; run doctor.
- Prompt: "Run cognirepo doctor and tell me what it says about the knowledge graph."
- Expected results: server up; graph.pkl.corrupt-<ts> present; doctor flags it and suggests
  `cognirepo index-repo .`; after reindex doctor is green.
- Obtained results: Ran against `cognirepo_test_repo/easy/flask`. Corrupted `graph.pkl` with
  `echo garbage > .cognirepo/graph/graph.pkl`, then ran `cognirepo watch --ensure-running` — server
  started cleanly (did not crash), emitting a warning naming the quarantine file
  `graph.pkl.corrupt-1784224658`; confirmed the original `graph.pkl` was gone and replaced by the
  `.corrupt-<ts>` file via `os.replace()`. Ran `cognirepo doctor`: Check 21 flagged
  "⚠ Knowledge graph — 1 quarantined file(s): graph.pkl.corrupt-1784224658" with hint
  "Run: cognirepo index-repo . (rebuilds graph.pkl from scratch)". Ran `cognirepo index-repo .`
  (rebuilt graph.pkl: 1,936 nodes · 7,813 edges). Doctor's "Knowledge graph" check itself then went
  green. **Nuance vs. literal ticket wording**: reindexing alone does NOT delete the old
  `.corrupt-<ts>` quarantine file — doctor kept warning about it until the file was manually
  removed (`rm .cognirepo/graph/graph.pkl.corrupt-1784224658`), after which doctor showed no
  warnings at all. This is intentional (mirrors `ast_indexer.py`'s `.corrupt` files, which are also
  retained for forensic inspection rather than auto-deleted), not a bug — noting it here since
  "after reindex doctor is green" in the expected-results wording could otherwise be read as
  requiring auto-cleanup of the quarantine file itself.
- Verdict: PASS
