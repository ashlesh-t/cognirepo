# COGNIREPO-601 — Manual test suite

## TC-601-1: Claims cross-check
- Test repo: /home/ashlesh/my_works/cognirepo
- Prerequisites: story merged.
- What to do: read README + METRICS as a skeptic; recompute one metric locally on
  cognirepo_test_repo/medium via `cognirepo benchmark --json`.
- Prompt: "List every benchmark claim in README.md and verify each against docs/METRICS.md and
  one live local run. Flag contradictions."
- Expected results: zero contradictions; local run within documented ranges; dates present.
- Obtained results: Cross-checked every benchmark claim in README.md against `docs/METRICS.md`:
  - README:18 (headline: 30–78% targeted / 96–99% naive, 5,900+ files) matches README:103-106's
    own table and `docs/METRICS.md`'s "Automated Benchmark Numbers"/"External Repo Validation"
    sections exactly (same 2026-09-17 run, same numbers).
    README:82-89 (30-prompt live-agent methodology, 6 repos) is clearly labeled as a distinct
    dataset (different measurement method: live Claude/Gemini/Cursor sessions, not `cognirepo
    benchmark --json`) — no longer silently conflated with the automated numbers as it was
    pre-story (originally the audit's finding: 4 vs 6 vs 4 repo counts read as if describing one
    measurement).
  - Live local re-run on `cognirepo_test_repo/medium/ansible` via `cognirepo benchmark --json`:
    `token_reduction_pct: 96.1`, `token_reduction_vs_targeted_pct: 28.6`,
    `context_relevance_pct: 56.6` — matches README:106/METRICS.md's ansible row exactly (same
    run, re-executed live for this test case rather than reusing the cached JSON).
  - Dates present: `docs/METRICS.md` top banner + Automated Benchmark section both say
    2026-09-17; README's external-repo table now carries "Measured 2026-09-17" too (was
    undated pre-story).
  - Zero contradictions found.
- Verdict: **PASS**
