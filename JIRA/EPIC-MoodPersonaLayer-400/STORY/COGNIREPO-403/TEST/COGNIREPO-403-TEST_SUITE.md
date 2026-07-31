# COGNIREPO-403 — Manual test suite

## TC-403-1: Style shifts, content survives (USER-FACING — user judges)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: 402+403 merged; MCP connected.
- What to do: ask the same nontrivial question persona-off then persona-on; diff the answers.
- Prompt: "Why would lookup_symbol return stale results after a file rename, and what fixes it?"
- Expected results: ON answer far shorter; BOTH contain the same root cause, the same file:line
  references, and the same caveats — nothing factual lost; verdict-first structure.
- Obtained results:
- Verdict:
