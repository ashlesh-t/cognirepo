# COGNIREPO-600-D02 — _BENCHMARK_QUERIES is CogniRepo-specific, skewing token_reduction/relevance/cache metrics on external repos

**Resolution (2026-09-17):** Added `_sample_repo_queries()` (same fallback ladder as
`_sample_repo_symbols`): repo-specific golden fixture → real symbol-sampled queries → hardcoded
`_DEFAULT_BENCHMARK_QUERIES` (renamed from `_BENCHMARK_QUERIES`) as last resort. All 3 call
sites in `run_benchmark()` updated to share one `_repo_queries = _sample_repo_queries(5)` call.
3 new regression tests; full suite green (1448 passed, 5 skipped, up from 1446). fastapi's
`token_reduction_pct` went from `0.0`/`details: []` to `97.6` across all 5 real queries; flask's
went from 1-of-5-queries-driven `33.5` to 5-of-5-queries-driven `97.3`. All 4 ACs PASS — see
TEST_SUITE for evidence.

Epic: COGNIREPO-600 · Branch: defect/COGNIREPO-600-D02 · Base: development
Found while re-running story COGNIREPO-601's benchmarks after COGNIREPO-600-D01 landed — the
`token_reduction_pct` numbers were still unreliable even with `REPO_ROOT` fixed.
Blocks: story COGNIREPO-601 (a benchmark re-run before this fix would publish another round of
unrepresentative numbers) and epic COGNIREPO-600 sign-off (per skill.md §G.4) until resolved.

## Backstory

`interface/tools/benchmark.py:410-415`:
```python
_BENCHMARK_QUERIES = [
    "store_memory implementation",
    "context_pack token budget",
    "hybrid_retrieve BM25 vector",
    "EpisodicMemory search episodes",
    "knowledge graph node edges",
]
```

This is CogniRepo's own internal vocabulary — symbol/concept names from CogniRepo's own source.
It's passed unchanged into `measure_token_reduction`, `measure_cache_speedup`, and
`measure_context_relevance` (`:465`, `:486`, `:492`) regardless of which repo is actually being
benchmarked. `_BENCHMARK_SYMBOLS` (`:418-424`) is the exact same shape of problem, and was
already fixed for `symbol_hit_rate` in v1.1.3 via `_sample_repo_symbols()` (samples real symbol
names from the target repo's own AST index, falling back to the hardcoded list only if the index
is empty) — but the analogous fix was never applied to `_BENCHMARK_QUERIES`.

Effect, confirmed 2026-09-17 with COGNIREPO-600-D01's `REPO_ROOT` fix already in place (so this
is not a re-observation of D01 — it's a second, independent bug in the same area):
- **fastapi**: `token_reduction_pct: 0.0`, `details: []`, `skipped: []` — all 5 queries hit
  `naive_raw == 0` (none of CogniRepo's own terms appear anywhere in fastapi's source), so
  `measure_token_reduction` silently produces no data at all rather than a real measurement.
  Confirmed by direct repro: `measure_token_reduction(_BENCHMARK_QUERIES)` against fastapi →
  `{"token_reduction_pct": 0.0, "details": [], "skipped": []}`.
- **flask**: `token_reduction_pct: 33.5` looked plausible in isolation, but direct repro shows
  it's driven by a **single** query out of five ("knowledge graph node edges" — "graph"/"node"
  happen to appear in flask's source) — `details` has exactly one entry. A number nominally
  averaged over 5 queries is actually a single unrepresentative sample.
- `measure_context_relevance` and `measure_cache_speedup` share the same `_BENCHMARK_QUERIES`
  input and are subject to the identical "wrong probe vocabulary" problem, though not
  independently repro'd with numbers here — the mechanism is the same.

This directly affects story COGNIREPO-601 AC2 ("fastapi row fixed or honestly explained — no
unexplained 0%") a second, independent way, and — more broadly — means `token_reduction_pct`
(the headline "50-80%" metric) has never actually measured "would CogniRepo help a user on
*this* repo" for any external repo; it measures "how many of CogniRepo's own internal terms
happen to appear in this repo's source," which is close to arbitrary.

## Description

Add `_sample_repo_queries(n: int = 5) -> list[str]`, following the same fallback shape as
`_sample_repo_symbols`:
1. Prefer the repo-specific golden fixture (`tests/fixtures/benchmark_golden_<repo>.json`,
   already exists for flask/fastapi/celery/ansible with hand-curated, repo-relevant queries) —
   reuses an existing, already-calibrated asset instead of inventing new sampling logic.
2. Else sample real symbol names from the target repo's own AST index (same mechanism
   `_sample_repo_symbols` already uses) and build simple queries from them.
3. Else fall back to `_BENCHMARK_QUERIES` (renamed `_DEFAULT_BENCHMARK_QUERIES` to make clear
   it's a last-resort fallback, not the primary probe set) — preserves current behavior when
   benchmarking CogniRepo itself, where its own vocabulary IS the relevant one.

Replace the three call sites (`:465`, `:486`, `:492`) with `_sample_repo_queries(5)`.

## Acceptance criteria
1. `token_reduction_pct` for fastapi is no longer `0.0`/`details: []` — real queries relevant to
   fastapi's own content are used.
2. `token_reduction_pct` for flask is driven by multiple (not one) real queries.
3. Benchmarking CogniRepo itself (no external repo) still works — `_BENCHMARK_QUERIES` fallback
   preserved.
4. Full pytest suite stays green.

## Risks / notes
- Pure measurement-tool correctness fix, no product-facing schema/storage change.
- Story 601's benchmark re-run happens after this lands, not before — same reasoning as D01.
