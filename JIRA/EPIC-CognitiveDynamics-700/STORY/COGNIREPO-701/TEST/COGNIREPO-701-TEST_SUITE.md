# COGNIREPO-701 — Manual test suite

## TC-701-1: Recent hits outrank stale hits of equal count
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: story merged; two symbols seeded with equal `hit_count` via `record_feedback`,
  one with `last_hit` backdated 6+ months, one left at "now".
- What to do: run a `context_pack` query that retrieves both symbols; compare their `behaviour_score`.
- Prompt: "Find where these two functions are used and rank them by relevance."
- Expected results: the recently-hit symbol scores higher despite equal historical hit_count.
- Obtained results:
- Verdict:

## TC-701-2: Fresh-data golden regression
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/dummy
- Prerequisites: story merged; fresh index, all behaviour hits timestamped "now".
- What to do: run the existing retrieval benchmark / a representative query set before and after
  701; diff the `behaviour_score` and `final_score` outputs.
- Prompt: "Run the retrieval benchmark and compare scores to the pre-701 baseline."
- Expected results: scores match v2.2.0 behavior within floating-point tolerance — no regression
  for data with no decay to apply.
- Obtained results:
- Verdict:
