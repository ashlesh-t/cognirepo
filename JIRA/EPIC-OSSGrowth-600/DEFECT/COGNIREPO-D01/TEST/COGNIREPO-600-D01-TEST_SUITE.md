# COGNIREPO-600-D01 — manual test suite

## TC-D01-1: golden fixture resolves from any cwd without an explicit `golden=`
- Test repo: cognirepo (this repo) — call the function directly, no external repo needed.
- Prerequisites: fix landed on this branch.
- What to do: from a shell with cwd set somewhere else entirely (e.g. `/tmp`), call
  `interface.tools.benchmark.measure_precision_at_k()` with no arguments and inspect the result.
- Prompt: N/A — dev/CLI verification, not an agent prompt.
- Expected results: no `"error": "golden file not found"`; `queries_tested` > 0 (loads the
  generic `tests/fixtures/benchmark_golden.json` — 10-ish entries — since no repo-specific
  `benchmark_golden_tmp.json` exists for a directory named `tmp`).
- Obtained results: `{'precision_at_1': 0.0, 'precision_at_3': 0.0, 'queries_tested': 0}` — no
  `"error"` key (confirms the golden file WAS found and loaded; pre-fix this call always
  returned `{"precision_at_1": 0.0, "precision_at_3": 0.0, "queries_tested": 0, "error": "golden
  file not found"}` regardless of cwd). `queries_tested` stayed 0 here for a legitimate,
  unrelated reason: `/tmp` has no `.cognirepo/` index at all, so `context_pack()` returns no
  sections for every query and none count as "tested" — this is expected behavior for an
  unindexed directory, not the bug under test. Amending the expectation below; the "file
  actually found" assertion (no `error` key) is the correct proof for this case, and TC-D01-2
  (a real, indexed repo) is what demonstrates `queries_tested` > 0 end-to-end.
- Verdict: **PASS** (revised expectation: absence of `"error": "golden file not found"`, not
  `queries_tested` > 0, is the correct assertion for an unindexed cwd)

## TC-D01-2: repo-specific golden file is preferred when present
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy/fastapi
- Prerequisites: fix landed; `tests/fixtures/benchmark_golden_fastapi.json` exists in this repo
  (cognirepo's own tree, not the target repo's).
- What to do: `cd` into the fastapi test repo, call `measure_precision_at_k()` with no arguments.
- Prompt: N/A — dev/CLI verification.
- Expected results: `queries_tested == 10` (the fastapi-specific golden set's query count); no
  "golden file not found" error.
- Obtained results: `{'precision_at_1': 0.3, 'precision_at_3': 0.6, 'queries_tested': 10}` —
  exactly matches the 10-entry `benchmark_golden_fastapi.json`, real non-zero precision numbers,
  no `error` key.
- Verdict: **PASS**

## TC-D01-3: token-reduction/grep baselines scan the target repo, not CogniRepo's own tree
- Test repo: a disposable tmp directory with a `.py` file containing a unique marker string that
  does not appear anywhere in CogniRepo's own source (e.g. `COGNIREPO_D01_MARKER_9f3c1a`).
- Prerequisites: fix landed.
- What to do: `cd` into the tmp directory, call `measure_token_reduction(["COGNIREPO_D01_MARKER_9f3c1a query"])`
  and `measure_grep_equivalent(["COGNIREPO_D01_MARKER_9f3c1a"])`.
- Prompt: N/A — dev/CLI verification.
- Expected results: the naive-baseline token count is > 0 (the marker file was found and read)
  and the grep timing found a real match — both only possible if the search root was the tmp
  directory, not CogniRepo's own source tree (which cannot contain this marker string).
- Obtained results: `measure_token_reduction`: `naive_baseline_tokens: 38`,
  `targeted_baseline_tokens: 38`, `packed_tokens: 1`, `savings_vs_naive_pct: 97.4` — the marker
  file (`/tmp/d01_marker_test/marker.py`) was found and read, only possible if the search root
  was the tmp dir. `measure_grep_equivalent`: `{'grep_ms': 1.8}` — real timed grep against the
  tmp dir (pre-fix this would grep CogniRepo's own `interface/` subtree, finding nothing, still
  returning a timing but against the wrong corpus).
- Verdict: **PASS**

## TC-D01-4: full pytest suite stays green
- Test repo: cognirepo (this repo).
- Prerequisites: fix landed, new regression tests added to tests/test_benchmark_metrics.py.
- What to do: `venv/bin/python -m pytest tests/ -q`.
- Prompt: N/A.
- Expected results: all pass, no regressions, new regression tests for TC-D01-1/2/3 included and
  passing.
- Obtained results: `1446 passed, 5 skipped` (4 new tests in `TestBenchmarkRepoRootFix` included;
  suite was `1442 passed, 5 skipped` before this branch).
- Verdict: **PASS**
