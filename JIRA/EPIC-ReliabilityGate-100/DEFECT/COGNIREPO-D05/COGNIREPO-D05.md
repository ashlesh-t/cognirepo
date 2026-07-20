# COGNIREPO-D05 — pending debounced events lost on watcher shutdown

Epic: COGNIREPO-100 · Branch: defect/COGNIREPO-D05 · Base: development

## Backstory
Found while implementing COGNIREPO-105 (layer-invariant cleanup). COGNIREPO-102 added
debounce/batching to the file watcher and wired the shutdown flush into
`BehaviourTracker.stop_watching()` (`data/graph/behaviour_tracker.py`, pre-105):

```python
def stop_watching(self) -> None:
    if self._observer is not None:
        handler = getattr(self._observer, "_cognirepo_handler", None)
        if handler is not None:
            handler.flush()
        self._observer.stop()
        self._observer.join()
```

`RepoFileHandler.flush()`'s own docstring (`intelligence/indexer/file_watcher.py:133-138`)
says it is "Called by the debounce timer, and by stop_watching() on shutdown so no queued
events are lost."

`BehaviourTracker.start_watching()`/`stop_watching()` are never called anywhere in the
codebase — `cognirepo watch` (`interface/cli/main.py:2140-2159`, foreground) and the
MCP-server-launched background watcher (`interface/cli/main.py:2190-2199`) both call
`intelligence.indexer.file_watcher.create_watcher()` directly and stop the returned observer
with a local closure:

```python
def _stop_observer(obs):
    obs.stop()
    obs.join()
```

— no `handler.flush()` call. `run_watcher_with_crash_guard`
(`interface/cli/daemon.py:182-226`) also never calls `flush()`. Net effect: any file change
still sitting in the debounce window (up to `debounce_ms`, default per `file_watcher.py`) at
the moment of Ctrl+C / SIGTERM / crash-guard restart is silently dropped — never indexed,
never graph-saved — because the flush machinery COGNIREPO-102 built is wired to a method
(`stop_watching()`) that no production code path calls.

(COGNIREPO-105 deletes `BehaviourTracker.start_watching()`/`stop_watching()` as dead code
while eliminating the `data → intelligence` upward import at behaviour_tracker.py:513 —
this defect is filed to make sure the *flush* behavior isn't lost along with them, since the
method was dead but the intent it encoded (flush-before-stop) was real and tested via
`tests/test_watcher_debounce.py`'s `flush()`-focused tests.)

## Description
Wire `handler.flush()` into the actual shutdown path(s) instead of the unreachable
`BehaviourTracker.stop_watching()`:
- `interface/cli/main.py:2143-2145` (`_stop_observer`, foreground `cognirepo watch`)
- `interface/cli/main.py:2193-2195` (`_stop`, MCP-launched background watcher thread)

Both already have `obs` (the Observer instance with `_cognirepo_handler` set by
`create_watcher()`, `file_watcher.py:305`) — call `obs._cognirepo_handler.flush()` (or add a
small helper) before `obs.stop()`, mirroring the intended `stop_watching()` sequence.

## Acceptance criteria
1. A file change inside the debounce window followed immediately by SIGTERM/Ctrl+C still gets
   indexed (fixture: short `debounce_ms`, write a file, signal within the window, assert
   `indexer.index_file` / `graph.save` were called before process exit).
2. Same for the MCP-launched background watcher path.
3. Existing `tests/test_watcher_debounce.py` stays green.

## Risks / notes
- Narrow window (only matters for edits made in the last `debounce_ms` before shutdown) but a
  real, silent data-loss bug — worth an epic-100 (ReliabilityGate) fix.
- Decide whether `BehaviourTracker.stop_watching()`'s removal (COGNIREPO-105) needs a
  replacement helper in `file_watcher.py` itself (e.g. `create_watcher()` returning a
  `(observer, stop_fn)` pair) rather than duplicating the flush-then-stop sequence at each
  call site.

## Corrections found during implementation
- **The initial fix (patching `_stop_observer`/`_stop` to call `_flush_and_stop_observer`) was
  not sufficient on its own.** The backstory above already named
  `run_watcher_with_crash_guard()` (`interface/cli/daemon.py`) as never calling `flush()`, but
  the first pass assumed patching the `stop_fn` closures was enough without checking that
  `run_watcher_with_crash_guard()` actually *calls* `stop_fn` on every exit path. It doesn't:
  `except KeyboardInterrupt:` (the branch SIGTERM/Ctrl+C actually take, since the installed
  signal handler raises `KeyboardInterrupt`) printed "stopped by user" and broke out of the loop
  without ever calling `stop_fn(observer)` — only the crash-recovery `except Exception:` branch
  did. This was caught by a genuine live TC-D05-1 walkthrough (real `cognirepo watch`, real
  edit, real `SIGTERM`, direct inspection of `ast_index.json`'s per-file `sha256`) that
  reproduced the exact data-loss bug even with the first patch applied. Fixed by also calling
  `stop_fn(observer)` in the `KeyboardInterrupt` branch, mirroring the crash branch's
  try/except-around-`stop_fn`. Re-ran the live walkthrough after this correction: PASS.
- **`cognirepo verify-index` is not a valid check for "was this edit flushed."** Its DIRTY
  detection compares source-file mtime against `manifest.json`'s `indexed_at`, which is only
  updated by full `index-repo` runs — not by the watcher's incremental `flush()` — so it
  reports DIRTY regardless of whether the watcher actually flushed the edit in time. TC-D05-1's
  own "then run cognirepo verify-index" step needs to be read as "then confirm the AST index
  reflects the edit" (e.g. via `ast_index.json`'s `sha256`/symbol list), not literally
  `verify-index`'s exit code.
