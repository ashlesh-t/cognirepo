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
