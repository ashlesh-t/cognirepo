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

## Corrections found during implementation
- **`watcher_factory` param dropped.** `BehaviourTracker.start_watching()`/`stop_watching()`
  (the data→intelligence case at behaviour_tracker.py:513, cited above) have zero callers
  anywhere in the codebase (confirmed via grep) — `cognirepo watch` and the MCP-launched
  background watcher both call `intelligence.indexer.file_watcher.create_watcher()` directly,
  bypassing BehaviourTracker entirely. Rather than add an unused `watcher_factory` DI param,
  both methods were deleted as dead code. This *is* the cleanest resolution of the upward
  import (no callback needed when there's no caller), but it surfaced that the shutdown-flush
  behavior COGNIREPO-102 wired into `stop_watching()` was itself unreachable — filed as
  `COGNIREPO-D05` since fixing it is a real behavior change, out of this ticket's
  "no behavior edits" scope.
- **AC2 "passes on HEAD" — two new violations found, one fixed, one deferred.**
  `scripts/build_import_graph.py`'s `INTERNAL_PACKAGES` set was stale (pre-2.0.0 flat names),
  so it matched zero real imports and `check_circular_deps.py` always trivially passed
  regardless of real violations. Fixed the package-root set (dev tooling, not runtime code —
  doesn't violate "no behavior edits"). Re-running against real data surfaced two *new*
  findings not in the original audit:
  - `interface/cli/main.py`'s `prune` handler importing `ops.cron.prune_memory` — a
    false positive: `interface/cli/*.py` was falling through `_pkg_of_file()`'s classification
    to generic `"interface"` (layer 3) instead of `"cli"` (layer 5), which `LAYER_MAP` already
    defines and `docs/ARCHITECTURE.md` already documents as the intended top-level-consumer
    layer. Fixed by special-casing the `interface/cli/` path prefix in `_pkg_of_file()`.
  - `core/vector_db/local_vector_db.py`'s `save()`/`suppress_row()` lazily importing
    `data.memory.circuit_breaker`/`cleanup_queue` — a real violation, but the dominant
    construction path (`get_vector_adapter()`, itself `core`-layer) can't legally wire the
    callbacks without becoming an upward import itself, and defaulting to `None` there would
    silently disable circuit-breaker protection for nearly all real callers — a genuine
    behavior regression, not in scope here. Deferred to `COGNIREPO-D06` per skill.md §G.
  - With the tooling fix + the `interface/cli` fix, `check_circular_deps.py` reports exactly
    the two `COGNIREPO-D06` findings and nothing else — i.e. it "passes on HEAD" modulo the
    one deferred defect, which is registered and tracked (parent epic cannot sign off with
    D06 open, per skill.md §G.4).
