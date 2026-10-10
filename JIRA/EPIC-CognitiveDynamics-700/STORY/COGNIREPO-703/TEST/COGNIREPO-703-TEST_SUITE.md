# COGNIREPO-703 — Manual test suite

## TC-703-1: Near-boundary query reports lower confidence than a decisive one
- Test repo: cognirepo (the tool's own repo — this is a classifier-internals test, not a
  target-codebase one)
- Prerequisites: story merged.
- What to do: run one hand-constructed near-boundary query (score ~3.9) and one decisively
  mid-tier query (score ~0.1) through the classifier; compare `confidence`.
- Prompt: "Classify these two example queries and tell me your confidence in each classification."
- Expected results: the near-boundary query reports visibly lower confidence than the decisive
  one; both still land in the same tier as pre-703 behavior.
- Obtained results: Hand-constructed via the real `classify()` function (not a mock): a
  36-token reasoning-keyword query landed at `score=3.85` (just under the 4.0
  STANDARD/COMPLEX boundary), `tier=STANDARD`, `confidence=0.15`. A short lookup-style query
  ("show me the get function config") landed at `score=-4.0`, `tier=QUICK`, `confidence=1.0`
  (capped — well clear of any boundary). 0.15 vs 1.0 is clearly measurably lower. Both tiers
  match what `_compute_score`/`_score_to_tier` alone would have produced pre-703 — confirmed by
  the fact neither function was touched by this change (`_confidence_from_score` is a new,
  separate function reading the already-computed score).
- Verdict: **PASS**

## TC-703-2: Tier assignment golden regression
- Test repo: cognirepo
- Prerequisites: story merged.
- What to do: run the full existing classifier test corpus before and after 703; diff tier
  assignments.
- Prompt: "Run the classifier test suite and confirm no tier assignment changed."
- Expected results: zero tier-assignment diffs — only the new `confidence` field is added.
- Obtained results: `tests/test_classifier.py` (27 tests, including a new golden-tier fixture
  set covering QUICK/STANDARD/COMPLEX/EXPERT and hard overrides) — 27/27 PASS. All pre-existing
  tier assertions unchanged and still pass, since `_compute_score`/`_score_to_tier` were not
  modified — `confidence` is computed by a new, separate `_confidence_from_score()` function
  reading the already-final score. Full suite: 1472 passed, 5 skipped (development's own
  baseline before this branch was 1465; +7 new `TestConfidence` tests). `signals` dict output
  (AC3) and `test_model_id_invariant.py`/`test_docs_sync.py` (AC4 — no model literals
  introduced, thresholds table still in sync) both verified unaffected.
- Verdict: **PASS**
