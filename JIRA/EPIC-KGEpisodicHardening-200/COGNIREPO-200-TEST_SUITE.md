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
- Obtained results:
- Verdict:

## E2E-200-2: Graph enrichment round-trip (crosses 201+202+203)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/advanced
- Prerequisites: epic merged; `cognirepo index-repo .` re-run so similarity + Go extraction land.
- What to do: pick two semantically similar functions in different files and one Go (or
  registry-pattern) call site; query subgraph, who_calls, graph_stats.
- Prompt: "Show me the subgraph around <function_a>; who calls <go_or_registry_fn>; then give me
  graph health stats."
- Expected results: subgraph includes the SIMILAR_TO counterpart; who_calls lists the verified
  caller(s); graph_stats shows integrity block with 0 orphans on the fresh index.
- Obtained results:
- Verdict:
