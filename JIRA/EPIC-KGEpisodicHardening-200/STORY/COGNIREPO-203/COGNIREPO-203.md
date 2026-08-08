# COGNIREPO-203 — Go call-graph completion + dynamic-dispatch annotation

Epic: COGNIREPO-200 · Branch: story/COGNIREPO-203 · Base: development

## Backstory
README.md:613-615 calls Go call-graph "the single highest-impact unblocked item"; current code
handles generic call_expression (ast_indexer.py:415 — JS/Java/Go) but Go selector-expression
method calls (x.Foo()) and method values are unproven, and README.md:626's plugin-registry
detection (Ansible register / entry_points / __init_subclass__ / Celery @app.task) is absent —
no DYNAMIC_DISPATCH anywhere in code. Evidence: ../../COGNIREPO-200-Discovery.md §1.

## Description
(1) Go: add selector_expression call extraction (receiver-qualified method calls) and IMPORTS
edges from go import specs to ast_indexer's Go handling; keep language_registry ↔
interface/cli/service_detect.py::_SERVICE_MARKERS in sync (CLAUDE.md rule — check, likely no
change since Go already registered). (2) Dispatch heuristics: a static pass flagging
entry_points (setup.cfg/pyproject), `register(`-style plugin calls, __init_subclass__, and
celery-style decorator tasks → node attr dispatch:"dynamic" + RELATES_TO edge to a CONCEPT
node "dynamic_dispatch". who_calls keeps its existing coverage_note behavior.

## Acceptance criteria
1. Go fixture: who_calls resolves ≥90% of a hand-verified caller list (fixture with ≥10 call
   sites incl. method calls).
2. Celery/Ansible-style fixture symbols carry dispatch:"dynamic".
3. tests/test_indexer_multilang.py extended for both; suite green.
4. No Python-path regressions (golden lookup tests unchanged).

## Risks / notes
- FIRST ACTION: check whether cognirepo_test_repo/advanced contains Go sources; if not, add a
  small Go fixture under tests/fixtures/ (TEST_SUITE marks this BLOCKED until resolved).
- Dispatch heuristics are annotation-only — they must not fabricate CALLS edges.

## Implementation notes (2026-08-08)
- FIRST ACTION resolved: cognirepo_test_repo/advanced/moby (Docker) has 9992 real .go files —
  no synthetic fixture needed for the live TEST_SUITE check. A hand-crafted inline fixture was
  still added to tests/test_indexer_multilang.py (TestGoIndexing) for a deterministic,
  version-controlled ≥10-call-site regression test per AC1/AC3.
- Root cause of the missing Go method-call resolution: tree-sitter's Go `selector_expression`
  names its method field `field`; the existing `_ts_collect_calls` only checked `property`
  (the JS/TS field name), so `recv.Method()` calls were silently dropped for every Go file
  ever indexed. Fixed with a fallback field lookup.
- A SECOND, independent bug surfaced during live verification against moby: `_ts_collect_calls`'s
  recursion depth cap (12) was too shallow for realistic nested code — a Go method wrapping an
  if-statement around `append(x, Struct{Field: recv.Method()})` alone reaches depth 12-13,
  dropping the innermost call. Raised the cap to 60. This affects call extraction for every
  supported language, not just Go, though Go's method+conditional+composite-literal style
  triggers it disproportionately.
- Dynamic-dispatch heuristic added as `_detect_dynamic_dispatch()` (decorators/`register()`
  calls/`__init_subclass__`) plus a separate post-index pass `_apply_entry_points_dispatch()`
  for pyproject.toml/setup.cfg entry-points — both annotation-only (`dispatch:"dynamic"` +
  `RELATES_TO` → `concept::dynamic_dispatch`), no fabricated CALLS edges (verified by test).
- language_registry ↔ service_detect.py::_SERVICE_MARKERS already in sync for Go — no change
  needed (confirmed per CLAUDE.md rule).
