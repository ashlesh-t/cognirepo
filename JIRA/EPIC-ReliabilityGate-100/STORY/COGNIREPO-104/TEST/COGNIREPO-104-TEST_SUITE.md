# COGNIREPO-104 — Manual test suite

## TC-104-1: Dirty detection
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy
- Prerequisites: story merged; cognirepo index-repo . completed on a clean tree.
- What to do: run verify-index (expect OK); append a comment to an indexed .py; run again.
- Prompt: "Run cognirepo verify-index before and after I touch a source file, and report both
  exit codes and outputs."
- Expected results: first run OK/exit 0; second run DIRTY line naming 1 file, exit 1; after
  `git checkout` of the file, OK again.
- Obtained results: Ran against `cognirepo_test_repo/easy/flask` (existing index: 1832 symbols ·
  92 files · commit `2ac89889f4cc`). First `verify-index`: `OK 1832 symbols · 92 files · commit
  2ac89889f4cc · indexed 2026-07-16T18:31:51.077693+00:00`, exit 0. Appended a comment line to
  the tracked, indexed `docs/conf.py`; re-ran after the ±2s clock-skew window: `OK` line
  unchanged plus a new `DIRTY  1 uncommitted indexed source file(s) newer than index` line
  naming `docs/conf.py`, with the rebuild hint, exit 1. Ran `git checkout -- docs/conf.py` to
  discard the edit; re-ran `verify-index`: back to plain `OK`, exit 0, no DIRTY line.
- Verdict: PASS
