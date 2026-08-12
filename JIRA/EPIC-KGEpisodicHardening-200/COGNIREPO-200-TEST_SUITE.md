# COGNIREPO-200 — Epic e2e test suite (cross-story flows only)

## E2E-200-1: "What happened in this repo?" in one call (crosses 204+205+201)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: epic merged; repo indexed; seed data: 2 sessions, 3 log_episode calls,
  1 record_decision, 1 record_error, plus enough events to trigger one rotation.
- What to do: call the timeline surface (get_timeline or get_agent_bootstrap digest) with
  include_archived on.
- Prompt: "Give me a timeline of everything that happened in this repo, including old history,
  and summarize it."
- Expected results: single tool call returns all seeded items chronologically ordered incl.
  rotated ones; rollup mentions the decision and the recurring error; no duplicate IDs.
- Obtained results: test repo `cognirepo_test_repo/medium/celery` (`.cognirepo/` backed
  up/restored around the test). `episodic_max_events` set to 20; seeded 2 sessions,
  3 log_episode, 1 record_decision, then 20 filler events (forced rotation — the 3
  episodes + decision, logged first, were the ones archived), then 1 recurring error
  (`BrokerConnectionError` x2). Single `data.memory.timeline.merge(include_archived=True)`
  call returned all 27 entries, newest first, correctly kind-labeled
  (`{"error": 1, "episode": 23, "decision": 1, "session": 2}`), 27/27 unique refs (no
  duplicates). `rollup()` named the decision (`"switch broker retry backoff to
  exponential"`) and the recurring error (`"BrokerConnectionError (x2)"`).
- Verdict: PASS

## E2E-200-2: Graph enrichment round-trip (crosses 201+202+203)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/advanced
- Prerequisites: epic merged; `cognirepo index-repo .` re-run so similarity + Go extraction land.
- What to do: pick two semantically similar functions in different files and one Go (or
  registry-pattern) call site; query subgraph, who_calls, graph_stats.
- Prompt: "Show me the subgraph around <function_a>; who calls <go_or_registry_fn>; then give me
  graph health stats."
- Expected results: subgraph includes the SIMILAR_TO counterpart; who_calls lists the verified
  caller(s); graph_stats shows integrity block with 0 orphans on the fresh index.
- Obtained results: `cognirepo_test_repo/advanced/moby` (`.cognirepo/` backed up/restored),
  freshly reindexed (116,532 symbols, 10,186 files, 0 orphans/dangling files per
  `graph_stats`). `who_calls('ResolvePath')` → 4 local callers, including both of
  TC-203-1's hand-verified pair (`CreateSecretSymlinks`, `CreateConfigSymlinks`) plus 2
  more Windows-path callers not present in TC-203-1's 22-file subset — full-repo index
  finds more, not fewer, callers. SIMILAR_TO: moby's 116,532 candidate symbols exceed
  `_SIMILARITY_SYMBOL_CEILING` (20,000, `ast_indexer.py:153`) — COGNIREPO-202's cost gate
  auto-disables k-NN similarity-edge building above that ceiling by design (moby's
  `config.json` doesn't override `indexing.similarity_edges`), so 0 SIMILAR_TO edges exist
  there. Not a defect — verified the SIMILAR_TO leg on `cognirepo_test_repo/medium/celery`
  instead (10,311 symbols, under the ceiling; same fixture TC-202-1 used): `subgraph
  ('_patch_gevent')` includes its cross-file SIMILAR_TO counterpart
  `t/unit/concurrency/test_gevent.py::test_is_patched` (cosine weight 0.847).
- Verdict: PASS (SIMILAR_TO leg verified on celery, not moby — moby's symbol count is
  by-design above the auto-similarity ceiling; documented, not a defect)
