# COGNIREPO-103 — Manual test suite

## TC-103-1: No orphans after symbol deletion
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy
- Prerequisites: story merged; indexed; watcher running; file with ≥2 functions.
- What to do: delete one function from the file, save, wait for reindex.
- Prompt: "Run graph_stats and lookup_symbol('<deleted_fn>'). Is there any trace of the deleted
  function?"
- Expected results: lookup empty; integrity/orphan count (post EPIC-200: explicit; here: node
  absent via subgraph('<deleted_fn>') returning empty).
- Obtained results:
- Verdict:

## TC-103-2: Corruption quarantine drill
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy
- Prerequisites: indexed; MCP server stopped.
- What to do: `echo garbage > .cognirepo/graph/graph.pkl`; start server; run doctor.
- Prompt: "Run cognirepo doctor and tell me what it says about the knowledge graph."
- Expected results: server up; graph.pkl.corrupt-<ts> present; doctor flags it and suggests
  `cognirepo index-repo .`; after reindex doctor is green.
- Obtained results:
- Verdict:
