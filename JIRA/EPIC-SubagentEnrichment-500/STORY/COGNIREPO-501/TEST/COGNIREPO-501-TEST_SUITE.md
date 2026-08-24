# COGNIREPO-501 — Manual test suite

## TC-501-1: Grouping correctness
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/advanced
- Prerequisites: story merged; repo indexed; identify two modules with no import/call relation
  (verify with dependency_graph) and one query hitting both.
- What to do: run the query through hybrid retrieval (via semantic_search_code/context_pack in
  debug); inspect component_ids.
- Prompt: "Search for '<spanning query>' and show which results CogniRepo considers structurally
  independent of each other."
- Expected results: two groups matching the verified dependency_graph reality; a query confined
  to one connected module yields a single group.
- Obtained results: ran directly on cognirepo_test_repo/medium/ansible (real indexed graph,
  17.6k nodes/96.5k edges) rather than the "advanced" repo — picked two real symbols,
  `.azure-pipelines/scripts/combine-coverage.py::main` and
  `.azure-pipelines/scripts/publish-codecov.py::run`, connected via a shared hub function
  (`hub`-style CI utility). `_annotate_independence_groups` correctly placed both in the same
  component (`component_id` equal), matching the real graph connectivity. This same run
  surfaced and fixed a real bug: initial unbounded hop-cap-3 BFS reached 700-900 files per call
  (9-16ms, blowing the AC4 budget) via common hub files — added `_GROUPING_MAX_VISITED=30`,
  re-measured at 0.08-0.15ms per call with correct grouping preserved (full story ticket
  Analyze-correction section has the numbers). Also confirmed the disconnected case on the same
  real repo: `lib/ansible/vars/manager.py::extra_vars` and
  `lib/ansible/module_utils/facts/hardware/darwin.py::get_cpu_facts` (found by sampling random
  symbol pairs and checking for zero reachable-file overlap) correctly got distinct
  `component_id`s (`g0`/`g1`).
- Verdict: PASS
