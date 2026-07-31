# COGNIREPO-601 — Benchmark truth + expansion

Epic: COGNIREPO-600 · Branch: story/COGNIREPO-601 · Base: development

## Backstory
README's benchmark story is internally inconsistent: 4 repos at README.md:18, 6 at :78, 4 at
:98, while docs/METRICS.md's automated table (:118-152) covers 3 (flask/fastapi/celery,
2026-06-17) with fastapi recall@1/@3 published as 0% "empty vector DB; under investigation" and
three metrics footnoted as fixed-in-1.1.3 but never re-run. A moby run (97.5% reduction,
recall@1 100%, 2026-06-12) exists in project memory but not in METRICS.md. Evidence:
../../COGNIREPO-600-Discovery.md §1.

## Description
(1) Root-cause fastapi recall (suspect area: interface/tools/benchmark.py golden/seed flow — the
analogous [1.1.3] bugs lived there, CHANGELOG.md:60-61). (2) Re-run `cognirepo benchmark --json`
at ≥2.2.0 on: flask, fastapi, celery, ansible, moby, kubernetes (user schedules the big two —
hours of indexing) + a cheap regression tier on cognirepo_test_repo/{easy,medium,advanced}.
(3) Replace METRICS.md tables with the dated new run; reconcile every README repo-count mention
to match; keep tests/test_benchmark_metrics.py thresholds green (adjust only with justification).

## Acceptance criteria
1. METRICS.md has one dated, current table; zero "fixed in 1.1.3, re-run pending" footnotes
   remain.
2. fastapi row fixed or honestly explained — no unexplained 0%.
3. README :18/:78/:98/:107 all agree with METRICS.md.
4. Local-fixture tier documented as reproducible-by-anyone.

## Risks / notes
- moby/k8s runs are user-machine-hours — the story can ship with those two marked "scheduled"
  if the user defers, but the counts must then say so honestly.
