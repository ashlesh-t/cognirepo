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
- Obtained results: (empty — this requires a live `cognirepo watch .` process against a real
  test repo + an actual SIGTERM/Ctrl+C; leaving for the user per skill.md §F.4.)
- Verdict:

Note: fix implemented and covered by an automated equivalent I could genuinely execute —
`_flush_and_stop_observer()` added in `interface/cli/main.py`, wired into both real shutdown
call sites (`_stop_observer` for foreground `cognirepo watch`, `_run()._stop` for the
MCP-launched background watcher). `tests/test_watcher_debounce.py::TestShutdownFlush` queues a
modify event with a 5s debounce window, calls `_flush_and_stop_observer(obs)` on a mock Observer
with `_cognirepo_handler` set, and asserts `indexer.index_file`/`indexer.save` were called
(pending event flushed) before `obs.stop()`/`obs.join()`. 7/7 passed
(`venv/bin/python -m pytest tests/test_watcher_debounce.py -q`).
