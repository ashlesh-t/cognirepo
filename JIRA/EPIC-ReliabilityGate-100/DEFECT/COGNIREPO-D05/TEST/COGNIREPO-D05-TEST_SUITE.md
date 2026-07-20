# COGNIREPO-D05 — Manual test suite

## TC-D05-1: Flush on Ctrl+C during debounce window
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy/flask
- Prerequisites: fix applied (flush wired into shutdown path).
- What to do: `cognirepo watch .` with a long debounce window, edit an indexed file, send
  SIGTERM/Ctrl+C within the window, then run `cognirepo verify-index`.
- Prompt: "Start the watcher, edit a file, stop the watcher immediately, then run verify-index
  — was the edit indexed before shutdown?"
- Expected results: post-shutdown, the edit is indexed (verify-index OK, not DIRTY, or the
  graph/AST index reflects the edit) — no silent event loss.
- Obtained results: Executed live against `cognirepo_test_repo/easy/flask` (real
  `cognirepo index-repo . --no-embed` foreground watcher, real SIGTERM, `debounce_ms` bumped to
  8000 in that repo's `.cognirepo/config.json` for a comfortable manual window):

  1. `cognirepo index-repo . --no-embed` — baseline index built (1832 symbols, 92 files).
  2. Watcher started in background (`nohup ... &`), waited for "Watching ... Ctrl+C to stop."
  3. Appended `def _cognirepo_tc_d05_marker(): pass` to `src/flask/helpers.py`, then
     `kill -TERM <pid>` ~1s later (well inside the 8s debounce window). Log showed
     `[watcher:...] stopped by user.` / `[watcher] stopped.`.
  4. **First run (before this fix): FAILED.** Inspecting `.cognirepo/index/ast_index.json`
     directly showed the entry's `sha256`/`indexed_at` unchanged from the pre-edit baseline and
     the new symbol absent — the edit was silently dropped exactly as D05 describes, even with
     `_stop_observer`/`_run()._stop` already patched to flush. Root-caused to
     `run_watcher_with_crash_guard()`'s `except KeyboardInterrupt` branch never calling
     `stop_fn(observer)` at all (only the crash/`except Exception` branch did) — SIGTERM's
     installed handler raises `KeyboardInterrupt`, so the primary real-world shutdown path
     bypassed the flush entirely. Fixed in `interface/cli/daemon.py` (see COGNIREPO-D05 commit
     history) — added the missing `stop_fn(observer)` call to the `KeyboardInterrupt` branch.
  5. **Second run (after this fix): PASSED.** Reverted the test edit, rebuilt the baseline
     index, repeated steps 1–3 identically. `ast_index.json`'s recorded `sha256` for
     `src/flask/helpers.py` now matches the post-edit file content
     (`fd81ac1e318baa54127ca9df9a00d5ca36b61716494cf0199257758feefc620a`) and the new
     `_cognirepo_tc_d05_marker` symbol is present in the index — the edit was flushed before
     the process exited.
  6. Note: `cognirepo verify-index` is NOT the right check here — its DIRTY detection compares
     file mtime against `manifest.json`'s `indexed_at` (set only by full `index-repo` runs, not
     by watcher flushes), so it reports DIRTY regardless of whether the watcher's incremental
     flush actually ran. Verified directly against `ast_index.json`'s per-file `sha256` instead.
  7. Cleaned up: reverted the test edit in the flask test repo (`git checkout --
     src/flask/helpers.py`); `.cognirepo/` there is gitignored/untracked, nothing to revert.
- Verdict: PASS (after the `run_watcher_with_crash_guard` KeyboardInterrupt fix — see step 4/5)

Also covered by an automated regression: `tests/test_cli_daemon.py::TestRunWatcherWithCrashGuardKeyboardInterrupt`
asserts `stop_fn(observer)` is called when the sleep loop is interrupted by `KeyboardInterrupt`,
and that a broken `stop_fn` doesn't crash the shutdown path. Plus the existing
`tests/test_watcher_debounce.py::TestShutdownFlush` covering `_flush_and_stop_observer()` itself.
4/4 and 7/7 passed respectively.
