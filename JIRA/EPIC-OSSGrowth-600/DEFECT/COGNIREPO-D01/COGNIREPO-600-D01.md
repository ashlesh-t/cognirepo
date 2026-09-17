# COGNIREPO-600-D01 — benchmark.py's REPO_ROOT points at the wrong tree (and the wrong repo)

**Resolution (2026-09-17):** Split `REPO_ROOT` into `_PACKAGE_ROOT` (CogniRepo's own install
root, fixed 3-parent path, used only for `tests/fixtures/` golden-set lookups) and
`_target_repo_root()` (returns `Path.cwd()`, used by `_read_files_for_query`,
`_targeted_baseline`, `measure_grep_equivalent` — the actual repo being benchmarked). All 6 call
sites updated. 4 new regression tests added (`TestBenchmarkRepoRootFix`); full suite green
(1446 passed, 5 skipped, up from 1442). All 4 ACs PASS — see TEST_SUITE for evidence.

Epic: COGNIREPO-600 · Branch: defect/COGNIREPO-600-D01 · Base: development
Found while investigating story COGNIREPO-601's fastapi memory-recall 0% (that specific issue
turned out to be a stale/transient artifact — re-running today gives `memory_recall_at_1/3: 1.0`,
not reproducible). Digging into the adjacent `precision_at_1/3: 0%` rows (blamed in
`docs/METRICS.md` on a "golden set bug fixed in v1.1.3") surfaced this, unrelated, still-live bug.
Blocks: story COGNIREPO-601 (a benchmark re-run before this fix would just publish more wrong
numbers) and epic COGNIREPO-600 sign-off (per skill.md §G.4) until resolved.

## Backstory

`interface/tools/benchmark.py:36`:
```python
REPO_ROOT = Path(__file__).parent.parent
```

This was correct when the file lived at `tools/benchmark.py` (one level below repo root).
Commit `719cf60` (2026-07-01, "refactor(core): establish core/ layer") moved it to
`interface/tools/benchmark.py` — one directory deeper — without updating the parent count.
`REPO_ROOT` now resolves to `.../cognirepo/interface`, not the actual repo root
`.../cognirepo`. Confirmed live via direct `python -c` reproduction (2026-09-17), see TEST_SUITE.

This one wrong constant is used for two conceptually different things, and both are broken:

**A. Locating CogniRepo's own `tests/fixtures/benchmark_golden_*.json`** (`measure_precision_at_k`
:279, `measure_latency`'s golden default :330, the aggregator's histogram golden load :487) —
looks under `interface/tests/fixtures/`, which doesn't exist, always falls through to
`"golden file not found"`. This is the actual, current cause of `precision_at_1`/`precision_at_3`
always reading `0.0` with `queries_tested: 0` — not the v1.1.3 issue METRICS.md blames (that one
really was fixed; the repo-specific-golden-file lookup logic v1.1.3 added is correct, it's just
never reached because the path built to check `.exists()` is wrong for both the repo-specific
*and* the generic fallback file).

**B. The "naive"/"targeted"/"grep" baselines used to compute `token_reduction_pct` and
`grep_ms`/`lookup_speedup_vs_grep_x`** — `_read_files_for_query` (:48), `_targeted_baseline`
(:67), and `measure_grep_equivalent` (:191) all take `REPO_ROOT` as the search root. These are
meant to answer "how many tokens would Claude read without CogniRepo, on the repo being
benchmarked" — i.e. they should scan the **target repo** (whatever `cognirepo benchmark` is
being run against — fastapi, flask, moby, …, resolved the same way `context_pack`/
`_sample_repo_symbols` do, via the ambient cwd/`.cognirepo/` state), not CogniRepo's own
source tree. Even with the parent-count in (A) fixed, `REPO_ROOT` as a **single fixed constant**
can never be right here, because it's the same value regardless of which repo you're
benchmarking. Every published `token_reduction_pct` and `grep_ms`/`lookup_speedup_vs_grep_x` for
every external repo has been comparing `context_pack`'s real, target-repo-scoped output against
a baseline built by grepping/reading CogniRepo's own `interface/` subtree (post-refactor) or
full source tree (pre-refactor, briefly correct-by-coincidence only in the sense that it grepped
*some* real tree, still the wrong one) — not the target repo at all.

No test caught either sub-bug: `tests/test_benchmark_metrics.py` always calls
`measure_precision_at_k(golden=[])`/`measure_latency(golden=[], ...)` with an explicit golden
list, bypassing the broken file-lookup path entirely, and nothing exercises
`measure_token_reduction`/`measure_grep_equivalent` against a real second repo at all.

## Description

1. Split the one constant into two, matching the two real concerns:
   - `_PACKAGE_ROOT = Path(__file__).parent.parent.parent` — CogniRepo's own install root, for
     locating its bundled `tests/fixtures/`.
   - A target-repo root resolved the same way the rest of the suite already does (ambient
     cwd — `Path.cwd()` — matching `_sample_repo_symbols`'s `KnowledgeGraph()`/`ASTIndexer`
     ambient resolution and `context_pack`'s), used by `_read_files_for_query`,
     `_targeted_baseline`, and `measure_grep_equivalent`.
2. Update all 6 call sites (`:111-112`, `:191`, `:279`, `:330`, `:487`) accordingly.
3. Add regression tests that actually exercise the broken paths — a golden fixture must be found
   without passing `golden=` explicitly (real `tests/fixtures/benchmark_golden.json` lookup,
   not a mocked/patched path), and `measure_token_reduction`/`measure_grep_equivalent` must be
   proven to scan a *different* directory than CogniRepo's own source when run with a different
   cwd.
4. Do not touch `docs/METRICS.md`/`README.md` numbers here — that's story COGNIREPO-601, which
   is blocked on this fix landing first (a re-run before the fix would just publish more wrong
   numbers under a fresh date).

## Acceptance criteria
1. `measure_precision_at_k()` (no explicit `golden=`) finds and loads
   `tests/fixtures/benchmark_golden.json` / `benchmark_golden_<repo>.json` correctly from any
   cwd; `queries_tested` is no longer unconditionally 0.
2. `measure_token_reduction`/`measure_grep_equivalent`, run from within a *different* repo's
   directory (e.g. `cognirepo_test_repo/easy/flask`), measure baselines against files in *that*
   repo, not CogniRepo's own source — demonstrated by a regression test using a tmp-dir fixture
   repo with content CogniRepo's own source doesn't contain.
3. Full pytest suite stays green; no change to `measure_memory_recall` (unaffected — resolves
   its own target repo correctly via `store_memory`/`retrieve_memory`'s ambient `.cognirepo/`
   state, never touched `REPO_ROOT`).

## Risks / notes
- This is a correctness fix to a *measurement* tool, not a product-facing feature — no schema
  change, no manifest-token growth, no `.cognirepo/` storage format change.
- Every historical benchmark number in `docs/METRICS.md` and every README repo-count/percentage
  claim derived from a benchmark run is now known-unreliable for `token_reduction_pct` and
  `grep_ms`-derived figures specifically (memory_recall/precision-golden-hit-rate/symbol-lookup
  numbers are unaffected — those never depended on `REPO_ROOT`). Story 601 re-runs everything
  fresh after this lands; no separate retraction/correction needed beyond that re-run.
