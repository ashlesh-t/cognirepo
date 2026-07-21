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
- Obtained results:
- Verdict:

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
