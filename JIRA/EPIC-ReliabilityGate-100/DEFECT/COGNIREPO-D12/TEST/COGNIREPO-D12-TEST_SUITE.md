# COGNIREPO-D12 — Manual test suite

## TC-D12-1: last_watcher_reindex.json written after flush()
- Test repo: /home/ashlesh/my_works/cognirepo (isolated `.cognirepo` test fixture)
- Prerequisites: fix applied.
- What to do: trigger a watcher `flush()` (add + remove in the same batch), inspect
  `.cognirepo/index/last_watcher_reindex.json`.
- Prompt: n/a — automated via a new `file_watcher` test.
- Expected results: file exists with a fresh timestamp, session id, and the reindexed/removed
  path lists matching the batch; a second flush overwrites (not appends).
- Obtained results:
- Verdict:

## TC-D12-2: Live re-run of E2E-100-1's failing sub-check (#1)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: fix merged; `cognirepo watch` running.
- What to do: burst-save one source file 5x in under 1 second.
- Prompt: n/a — direct filesystem check.
- Expected results: `.cognirepo/index/last_watcher_reindex.json` reflects the burst with one
  fresh timestamp (still one reindex per burst, per COGNIREPO-102's debounce contract).
- Obtained results:
- Verdict:
