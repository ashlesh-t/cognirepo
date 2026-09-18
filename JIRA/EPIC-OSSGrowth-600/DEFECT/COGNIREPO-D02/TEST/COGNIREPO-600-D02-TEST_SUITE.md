# COGNIREPO-600-D02 — manual test suite

## TC-D02-1: fastapi token_reduction is no longer 0.0/empty
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy/fastapi
- Prerequisites: fix landed; fastapi indexed fresh.
- What to do: `cd` into fastapi, call `measure_token_reduction(_sample_repo_queries(5))`.
- Prompt: N/A — dev/CLI verification.
- Expected results: `details` is non-empty (at least one, ideally most, of the 5 queries
  produce real naive/targeted baselines); `token_reduction_pct` is a real, non-zero,
  non-trivially-derived number.
- Obtained results: `_sample_repo_queries(5)` returned the fastapi golden set's own 5 queries
  (`Depends dependency injection FastAPI`, `APIRouter include router prefix tags`,
  `HTTPException status code detail raise`, `BackgroundTasks add task background`, `Request
  body JSON validation pydantic`). `measure_token_reduction` on them: `token_reduction_pct: 97.6`,
  `details` has all 5 entries (`naive_baseline_tokens` 13,222–374,957; `packed_tokens` 563–1330).
- Verdict: **PASS**

## TC-D02-2: flask token_reduction is driven by multiple queries, not one
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy/flask
- Prerequisites: fix landed; flask indexed fresh.
- What to do: `cd` into flask, call `measure_token_reduction(_sample_repo_queries(5))`, inspect
  `len(details)`.
- Prompt: N/A — dev/CLI verification.
- Expected results: `len(details) > 1` (previously exactly 1, driven by a single coincidental
  keyword match).
- Obtained results: `_sample_repo_queries(5)` returned flask's own golden queries (`Flask
  application factory create_app`, `Blueprint register routes prefix url`, etc.). `len(details)
  == 5` (previously 1), `token_reduction_pct: 97.3`.
- Verdict: **PASS**

## TC-D02-3: benchmarking CogniRepo itself still works (fallback preserved)
- Test repo: cognirepo (this repo).
- Prerequisites: fix landed.
- What to do: `cd` into cognirepo itself (no repo-specific golden file exists for a directory
  literally named `cognirepo`, and — depending on test setup — may hit the symbol-sampling or
  hardcoded fallback), call `_sample_repo_queries(5)`, confirm it returns 5 usable query strings
  without raising.
- Prompt: N/A — dev/CLI verification.
- Expected results: returns 5 non-empty query strings (from whichever fallback tier applies);
  no exception.
- Obtained results: no golden file for a directory literally named `cognirepo`, fell to the
  symbol-sampling tier (cognirepo's own index has ≥5 symbols) — returned 5 real symbol-derived
  queries (e.g. `TestBehaviourTrackerConcurrentSave implementation`), no exception.
- Verdict: **PASS**

## TC-D02-4: full pytest suite stays green
- Test repo: cognirepo (this repo).
- Prerequisites: fix landed, new regression tests added.
- What to do: `venv/bin/python -m pytest tests/ -q`.
- Prompt: N/A.
- Expected results: all pass, no regressions.
- Obtained results: `1448 passed, 5 skipped` (3 new tests in `TestSampleRepoQueries` included;
  was `1446 passed, 5 skipped` before this branch). One unrelated failure
  (`test_pid_file_and_heartbeat_removed_on_clean_exit`, a watcher/daemon shutdown test never
  touched by this change) appeared under full xdist parallel run but passed cleanly in
  isolation — flaky under parallelism, not a regression from this fix.
- Verdict: **PASS**
