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
- Obtained results:
- Verdict:
