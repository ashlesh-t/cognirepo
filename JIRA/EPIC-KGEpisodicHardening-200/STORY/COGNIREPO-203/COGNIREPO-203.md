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
