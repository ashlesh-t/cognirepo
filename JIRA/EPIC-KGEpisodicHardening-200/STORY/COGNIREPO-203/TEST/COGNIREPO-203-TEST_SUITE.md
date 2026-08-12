# COGNIREPO-203 — Manual test suite

## TC-203-1: Go caller resolution
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/advanced/moby — CONFIRMED it contains
  real Go sources (Docker/moby, 9992 .go files); BLOCKED note resolved, no synthetic fixture
  needed. Indexed a 22-file subset (daemon/container/) in isolation for tractable indexing time.
- Prerequisites: story merged; repo (re)indexed.
- What to do: hand-list the callers of two exported Go methods (grep -n "\.Fn(" *.go, cross-
  checked against enclosing func line ranges); compare against `cognirepo who-calls <Fn>`.
- Prompt: "Who calls ResolvePath? Who calls ConfigsDirPath? Give file:line for each caller."
- Expected results: ≥90% of the hand-verified list returned with correct locations; coverage
  note honest about the remainder.
- Obtained results: Hand-verified callers — ResolvePath: {CreateSecretSymlinks (line 37),
  CreateConfigSymlinks (line 87)}; ConfigsDirPath: {ConfigMounts (line 111), ConfigFilePath
  (line 206)}. `who-calls ResolvePath` returned both (source:"graph"), plus the same 2 sites
  again via the pre-existing text-scan fallback (found_via:"go_receiver_fallback", expected/
  harmless — coverage_note fires whenever the static graph alone returns ≤2 callers).
  `who-calls ConfigsDirPath` initially returned only ConfigFilePath (1/2) — investigation
  found a second, independent bug: `_ts_collect_calls`'s recursion depth cap (12) was too
  shallow for real code (a method + if-statement + `append(x, Struct{Field: recv.Method()})`
  composite literal alone reaches depth 12-13), silently dropping the ConfigsDirPath() call
  inside ConfigMounts's composite literal. Raised the cap to 60 (ast_indexer.py::
  _ts_collect_calls) and confirmed both hand-verified pairs resolve via the graph after
  reindexing. Final: 4/4 hand-verified callers resolved (100%, exceeds the 90% target).
- Verdict: PASS

## TC-203-2: Dynamic dispatch annotation
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium/celery
  (examples/django/demoapp/tasks.py — real `@shared_task`-decorated functions).
- Prerequisites: as above.
- What to do: query the symbol via lookup_symbol/subgraph.
- Prompt: "Look up add — does CogniRepo know it's dynamically dispatched?"
- Expected results: node carries dispatch:"dynamic"; subgraph links the dynamic_dispatch
  concept.
- Obtained results: `cognirepo subgraph add` on the indexed tasks.py fixture shows all 7
  `@shared_task`-decorated functions (add, mul, xsum, count_widgets, rename_widget, error_task,
  error_backoff_test) carrying `"dispatch": "dynamic"`, each with a `RELATES_TO` edge to a
  `concept::dynamic_dispatch` CONCEPT node. No fabricated CALLS edges observed.
- Verdict: PASS
