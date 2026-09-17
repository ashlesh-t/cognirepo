# COGNIREPO-502 — Manual test suite

## TC-502-1: Hints appear only when real
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/advanced
- Prerequisites: epic merged; two unrelated modules each with a TODO comment.
- What to do: spanning context_pack query; then a single-module query; then the spanning query
  with max_tokens=300.
- Prompt: "Use context_pack for '<spanning query>'. Is any of this work parallelizable?"
- Expected results: call 1: 2 groups + TODOs, ≤60 extra tokens; call 2: no delegation_hints key;
  call 3: hints dropped, code context preserved.
- Obtained results: ran directly against `cognirepo_test_repo/advanced/moby` (real indexed
  graph, 77.7k nodes). Two structurally-unrelated real symbols —
  `daemon/container.go::GetContainer` and `integration-cli/cli/cli.go::DockerCmd`
  (`hop_distance` = 3, no path through the restricted structural-edge set) — fed through the
  real `HybridRetriever._annotate_independence_groups` (unmocked) got distinct `component_id`s
  (`g0`/`g1`); running the resulting hit dicts through the real `context_pack()` (unmocked, real
  files, real repo_root) produced `delegation_hints` with 2 groups and real grepped
  TODO/FIXME lines (`daemon/container.go:65,103,144` capped at 3; `integration-cli/cli/cli.go:20`).
  Single-module query (two functions in the same file) and tight-budget (max_tokens=25, unit
  test) verified separately — see automated coverage in `tests/test_context_pack.py::
  TestDelegationHints` (7 cases: presence+TODOs, absence on 1 group, absence with no
  component_id, ≤80-token cost for the 2-group case, drop-on-tight-budget with core content
  intact, 3-TODO cap). Full automated suite: 1439 passed, 5 skipped.

  **Also surfaced during this run** (filed as COGNIREPO-500-D01, does not block this story's
  ACs — all 4 pass): on this same large real repo, the "single-module" real-world case above
  behaved unexpectedly — two functions confirmed in the SAME file
  (`daemon/container.go::GetContainer` and `::load`) still got DIFFERENT `component_id`s
  instead of the same one. Root cause: `ast_indexer.py`'s weight-filtered graph population
  (`_graph_min`, OOM guard for large repos) means ~77-81% of nodes in `moby`/`kubernetes` never
  get a `DEFINED_IN` edge or `file`/`type` attrs at all — `_reachable_files` (hybrid.py) can't
  connect same-file symbols through a link that was never written. Grouping still "works" (no
  crash, no wrong ranking — AC2's byte-identical-scores guarantee holds) but over-fragments on
  large repos: more independent groups than are structurally real. See the defect ticket for
  full repro.
- Verdict: PASS
