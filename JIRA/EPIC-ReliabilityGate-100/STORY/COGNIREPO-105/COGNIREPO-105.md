# COGNIREPO-105 — Layer-invariant cleanup (remove upward imports)

Epic: COGNIREPO-100 · Branch: story/COGNIREPO-105 · Base: development

## Backstory
The 2.0.0 restructure enforces core→data→intelligence→interface→ops via
scripts/check_circular_deps.py and claims 0 violations — true only at module level. The audit
found 5 runtime lazy upward imports into interface.* plus data→intelligence skips
(../../COGNIREPO-100-Discovery.md §1b): behaviour_tracker.py:540 (store_memory — the exact case
IMPROVEMENTS.md:9-23 documents with a suggested injectable-callback fix),
context_builder.py:270 (_write_manifest), summarizer.py:395/:451 and ast_indexer.py:1911
(bg_progress UI), cross_service_path.py:62/:128 and behaviour_tracker.py:513 (data→intelligence).

## Description
Eliminate each runtime upward import via dependency injection with None defaults (behavior
unchanged): BehaviourTracker gains store_fn + watcher_factory params supplied by interface-layer
callers; summarizer/ast_indexer gain an optional progress callback; context_builder's manifest
write moves to the interface caller; cross_service_path receives its indexer/router from
callers. Teach scripts/check_circular_deps.py to also scan function-body imports and fail on
upward ones (allowlist TYPE_CHECKING). Refresh IMPROVEMENTS.md (its item 1 resolved; item 2
resolved by D01/101; item 3 stays historical).

## Acceptance criteria
1. `grep -rn "from interface" data/ intelligence/ core/ --include='*.py'` → only TYPE_CHECKING
   hits.
2. check_circular_deps.py detects a deliberately-added lazy upward import (self-test) and passes
   on HEAD.
3. Full pytest green; no public API break (new params keyword-only with defaults).

## Risks / notes
- Widest-touch story of the epic; keep each injection mechanical, no behavior edits.
- data→intelligence cases may need an interface-layer wiring point (e.g. mcp_server constructs
  BehaviourTracker with the watcher factory) — follow the IMPROVEMENTS.md pattern.
