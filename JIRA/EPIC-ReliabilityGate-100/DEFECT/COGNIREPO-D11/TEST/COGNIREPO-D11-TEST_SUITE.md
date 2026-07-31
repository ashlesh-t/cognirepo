# COGNIREPO-D11 — Manual test suite

## TC-D11-1: Dirty check fires immediately after a live-watcher-style save
- Test repo: /home/ashlesh/my_works/cognirepo (isolated `.cognirepo` test fixture)
- Prerequisites: fix applied (`_check_working_tree_dirty` using `git status --porcelain` as
  the authoritative signal).
- What to do: index a repo, mutate a tracked file, immediately call `save()` (no sleep,
  simulating a live watcher refreshing `indexed_at`), then run the dirty check.
- Prompt: n/a — automated via `tests/test_verify_index_dirty.py`.
- Expected results: dirty check still reports the path as dirty despite `indexed_at` being
  newer than the old mtime-based heuristic would have allowed.
- Obtained results: `test_dirty_flagged_even_when_watcher_just_refreshed_indexed_at` — wrote
  the manifest (indexed_at = now) immediately after mutating `mod.py`, no sleep at all
  (previously this would have raced the old mtime-vs-indexed_at check). `verify-index`
  exits 1 with a `DIRTY` line naming `mod.py`. Also removed the now-unnecessary
  `time.sleep(2.5)` from all 5 pre-existing scenarios — they still pass (now for the correct
  reason: `git status --porcelain`, not mtime timing) and the suite runs in 1.59s instead of
  6.59s. `venv/bin/python -m pytest tests/test_verify_index_dirty.py -q` — 6 passed.
- Verdict: PASS

## TC-D11-1b: doctor surfaces the same finding as a non-fatal WARN
- Test repo: /home/ashlesh/my_works/cognirepo (isolated `.cognirepo` test fixture, real git repo)
- Prerequisites: fix applied (`doctor()` wired to `_check_working_tree_dirty`).
- What to do: real git repo, commit a file, edit it uncommitted, write a real manifest.json,
  call `_cmd_doctor()` directly (not the heavy in-process module-stub harness used elsewhere
  in `tests/test_doctor.py`, since this check shells out to real `git status`).
- Prompt: n/a — automated via `tests/test_doctor.py::TestDoctorWorkingTreeDirty`.
- Expected results: `WARN` line containing "Working tree", "uncommitted indexed source
  file", and a pointer to `cognirepo verify-index`; not escalated to a hard `✗` failure; a
  clean tree produces no such line at all.
- Obtained results: both `test_dirty_tree_produces_warn_not_hard_failure` and
  `test_clean_tree_no_working_tree_warning` pass as described.
  `venv/bin/python -m pytest tests/test_doctor.py -q` — 16 passed (was 14 before this
  ticket's 2 new tests).
- Verdict: PASS

## TC-D11-2: Live re-run of E2E-100-1's failing sub-checks (#4 and #5)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: fix merged; `cognirepo watch` running; 3 live uncommitted mutations present
  (rename, edit, delete) as in E2E-100-1.
- What to do: run `cognirepo verify-index` and `cognirepo doctor`.
- Prompt: n/a — direct CLI invocation.
- Expected results: `verify-index` exits 1 with a `DIRTY` line naming the mutated paths;
  `doctor` prints a `WARN` line referencing `verify-index`, exit code otherwise unaffected.
- Obtained results:
- Verdict:
