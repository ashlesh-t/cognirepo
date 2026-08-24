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
- Obtained results:
- Verdict:

## TC-703-2: Tier assignment golden regression
- Test repo: cognirepo
- Prerequisites: story merged.
- What to do: run the full existing classifier test corpus before and after 703; diff tier
  assignments.
- Prompt: "Run the classifier test suite and confirm no tier assignment changed."
- Expected results: zero tier-assignment diffs — only the new `confidence` field is added.
- Obtained results:
- Verdict:
