# COGNIREPO-601 — Manual test suite

## TC-601-1: Claims cross-check
- Test repo: /home/ashlesh/my_works/cognirepo
- Prerequisites: story merged.
- What to do: read README + METRICS as a skeptic; recompute one metric locally on
  cognirepo_test_repo/medium via `cognirepo benchmark --json`.
- Prompt: "List every benchmark claim in README.md and verify each against docs/METRICS.md and
  one live local run. Flag contradictions."
- Expected results: zero contradictions; local run within documented ranges; dates present.
- Obtained results:
- Verdict:
