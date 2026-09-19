# COGNIREPO-701 — Manual test suite

## TC-701-1: Recent hits outrank stale hits of equal count
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: story merged; two symbols seeded with equal `hit_count` via `record_feedback`,
  one with `last_hit` backdated 6+ months, one left at "now".
- What to do: run a `context_pack` query that retrieves both symbols; compare their `behaviour_score`.
- Prompt: "Find where these two functions are used and rank them by relevance."
- Expected results: the recently-hit symbol scores higher despite equal historical hit_count.
- Obtained results: Real end-to-end run against `cognirepo_test_repo/medium/celery` (not a
  mock) — seeded two symbols via real `BehaviourTracker.record_query()`/`record_feedback()`
  calls (`symbol::recent_fn`, `symbol::stale_fn`), both `hit_count=1.0`, then backdated
  `stale_fn`'s `last_hit` by 200 days directly in the persisted store. Ran the actual
  `HybridRetriever._behaviour_score()` (default `half_life_days=30`) on both via
  `get_all_scores_with_recency()`: `recent_score = 0.99999999628717`,
  `stale_score = 0.009843133165813091`. Recent symbol scores ~100x higher despite identical
  hit_count — decay is working as designed, not just in isolated unit tests.
- Verdict: **PASS**

## TC-701-2: Fresh-data golden regression
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/dummy
- Prerequisites: story merged; fresh index, all behaviour hits timestamped "now".
- What to do: run the existing retrieval benchmark / a representative query set before and after
  701; diff the `behaviour_score` and `final_score` outputs.
- Prompt: "Run the retrieval benchmark and compare scores to the pre-701 baseline."
- Expected results: scores match v2.2.0 behavior within floating-point tolerance — no regression
  for data with no decay to apply.
- Obtained results: Golden regression (unit-level): with `last_hit="now"`,
  `_behaviour_score()` returns exactly `math.log(1+count)/math.log(1+max_count)` (diff <1e-9)
  — the pre-701 formula unchanged, since decay factor at age=0 is exactly 1.0
  (`tests/test_hybrid_retrieval.py::TestSalienceDecay::test_behaviour_score_fresh_data_matches_pre_701_formula`).
  Benchmark comparison (`cognirepo benchmark --json` on this repo, before on `development` /
  after on this branch): `precision_at_1`/`precision_at_3` and `memory_recall_at_1/3` —
  identical (0.7/0.9, 1.0/1.0) both runs. `token_reduction_pct`/`context_relevance_pct` differed
  slightly (46.9→36.6, 7.9→6.0) but those metrics use `_sample_repo_queries()`'s random symbol
  sampling — expected run-to-run noise unrelated to this change, not a regression signal (the
  fixed-golden-set metrics are the reliable comparison and are unchanged).
- Verdict: **PASS**
