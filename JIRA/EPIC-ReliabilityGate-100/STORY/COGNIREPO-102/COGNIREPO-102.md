# COGNIREPO-102 — File-watcher hardening: debounce, rename handling, batched saves

Epic: COGNIREPO-100 · Branch: story/COGNIREPO-102 · Base: development

## Backstory
The user's most-repeated pain point ("indexing will not proper and stale"). Audit evidence
(../../COGNIREPO-100-Discovery.md §3): intelligence/indexer/file_watcher.py fires _reindex()
synchronously per watchdog event with NO debounce (README.md:616 roadmap item confirmed);
handles only on_modified/on_created/on_deleted — a `git mv` (FileMovedEvent) leaves the old
path in the AST index, reverse index and graph while the new path stays unindexed; and every
single event triggers full indexer.save() + graph.save() (file_watcher.py:153-154).

## Description
Add to RepoFileHandler: (1) an event queue with per-path dedupe flushed on a debounce timer
(default 500 ms; config key indexing.debounce_ms in config.json, document in CONFIGURATION.md);
(2) on_moved handler = _remove(src_path) + _reindex(dest_path); (3) one indexer.save() +
graph.save() + invalidate_hybrid_cache() per flushed batch instead of per event. Keep the
existing _reindex/_remove logic per unique path. New tests/test_watcher_debounce.py; extend
tests/test_stale_cleanup.py for the move case.

## Acceptance criteria
1. 5 modify events for one file within the window → exactly one index_file call and one save.
2. Move event: reverse index + graph contain dest path entries; zero src path entries.
3. Debounce window configurable; 0 disables (current behavior).
4. Existing watcher tests stay green.

## Risks / notes
- Timer thread must be a daemon and flush on stop_watching() so no events are lost on shutdown.
- 500 ms default is a guess — validate on the medium test repo with an editor burst.
- COGNIREPO-103 touches the same file; merge this first.

## Resolution

`intelligence/indexer/file_watcher.py`:
- `RepoFileHandler` gained a `debounce_ms` constructor param (default: read from
  `.cognirepo/config.json` → `indexing.debounce_ms`, falling back to 500) plus a per-path
  `_pending` dict guarded by a `threading.Lock` and a single `threading.Timer` (daemon=True).
  `on_modified`/`on_created`/`on_deleted` now call `_queue(action, path)`, which either processes
  the event synchronously (debounce_ms <= 0 — preserves the pre-102 behavior) or dedupes it into
  `_pending` (last action for a path wins) and (re)arms the timer.
- New `on_moved(event)` handler queues `"remove"` for `src_path` and `"reindex"` for `dest_path`,
  each gated by `is_supported()`.
- `flush()` drains `_pending` and processes every entry via new mutate-only helpers
  (`_reindex_mutate`/`_remove_mutate` — same logic as `_reindex`/`_remove` minus the
  save/side-effect tail), then does exactly one `indexer._build_reverse_index()` +
  `indexer.save()` + `graph.save()` for the whole batch, one `behaviour.save()` if anything was
  reindexed, per-removed-path `mark_stale()` calls, and one `invalidate_hybrid_cache()` if
  anything changed.
- `create_watcher()` attaches the handler to the returned `Observer` as `_cognirepo_handler` so
  callers can reach it for a shutdown flush.
- `data/graph/behaviour_tracker.py`'s `stop_watching()` now calls `handler.flush()` (via
  `_cognirepo_handler`) before `observer.stop()`/`.join()`, so no queued events are lost on
  shutdown per the ticket's risk note.

Docs: added `indexing.debounce_ms` (default `500`, `0` disables batching) to
`docs/CONFIGURATION.md`'s field table and example config block.

Tests:
- `tests/test_watcher_debounce.py` (new) — AC1 (5 modifies collapse to one `index_file`/save/
  graph.save/behaviour.save), AC3 (debounce_ms=0 synchronous passthrough; a custom window is
  honored; `flush()` is a no-op with nothing pending and processes immediately when called
  directly, e.g. from `stop_watching()`).
- `tests/test_stale_cleanup.py` — `TestFileWatcherRemove._make_handler` now passes
  `debounce_ms=0` so the existing per-event assertions keep testing synchronous behavior (AC4);
  added `test_on_moved_removes_src_and_reindexes_dest` for the move case (AC2).
- `tests/test_multilang_indexer.py` — `TestWatchdogCoverage._make_handler` likewise passes
  `debounce_ms=0` (its tests assert `on_modified` calls `_reindex` synchronously via
  `patch.object`).
- Full suite: `venv/bin/python -m pytest tests/ -q` → 1217 passed, 5 skipped.

Manual TEST_SUITE: both TC-102-1 and TC-102-2 executed live against
`cognirepo_test_repo/medium/celery` with `cognirepo watch --ensure-running` — PASS (see
TEST_SUITE.md for on-disk mtime/index evidence).

### PR review — round 1 (unrelated CI failure)
Reviewer flagged CI's `pip-audit` failing on `setuptools==81.0.0` (PYSEC-2026-3447, fixed in
83.0.0) — a pre-existing vulnerable pin unrelated to this story's code changes, surfaced only
because it's on the PR's CI run. Fixed:
- `requirements.txt`: `setuptools` 81.0.0 → 83.0.0.
- `.github/workflows/security.yml`'s "pyproject install" pip-audit job: explicitly upgrades
  `setuptools>=83.0.0` before `pip install .`, since that job's base-image setuptools was never
  otherwise upgraded (pyproject.toml's `requires = ["setuptools>=61.0"]` is a loose floor, not an
  upgrade instruction).
- Re-running `pip-audit -r requirements.txt` after the setuptools bump surfaced a second,
  independently-disclosed CVE — `httplib2==0.31.2` (PYSEC-2026-3444, fixed in 0.32.0) — bumped to
  0.32.0 so the CI gate passes cleanly rather than trading one red check for another.
- Verified: `pip-audit -r requirements.txt` (with the 3 existing documented ignores) →
  "No known vulnerabilities found, 1 ignored". Full suite re-run: 1217 passed, 5 skipped.
