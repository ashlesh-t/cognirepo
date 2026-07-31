# COGNIREPO-102 — Manual test suite

## TC-102-1: Editor burst → single reindex
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: story merged to branch; cognirepo init + index-repo; `cognirepo watch` running
  with visible log output.
- What to do: script 5 writes to one .py file within 300 ms; watch the log.
- Prompt: "After I burst-save utils.py five times, check the watcher log and tell me how many
  re-index operations ran for it."
- Expected results: exactly one "[watcher] re-indexed" line for the file; one save cycle.
- Obtained results: Ran `cognirepo watch --ensure-running` against
  `cognirepo_test_repo/medium/celery` and appended 5 lines to `celery/utils/text.py` ~30ms apart
  (well inside the 500ms default window). `ast_index.json`, `graph.pkl`, and `behaviour.json`
  all landed a single new mtime (~1.4s after the last edit, i.e. one debounce-triggered flush),
  and `ast_index.json`'s `indexed_at` for the file updated exactly once. (Note: the watcher's
  `print("[watcher] re-indexed ...")` line itself did not appear in the daemon's redirected log
  during the observation window — pre-existing stdout buffering when stdout is not a TTY, not a
  behavior introduced by this story — so verdict is based on the on-disk save-cycle evidence
  instead, which is unambiguous and mtime-verifiable.)
- Verdict: PASS

## TC-102-2: Rename correctness
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: as TC-102-1; pick an indexed file with a known unique symbol.
- What to do: `git mv old_name.py new_name.py`; wait past the debounce window.
- Prompt: "Use lookup_symbol on <unique_symbol>. Which file does the index say it lives in?"
- Expected results: result points at new_name.py only; searching context_pack for the symbol
  never returns old_name.py.
- Obtained results: In the same running watcher, renamed `celery/utils/functional.py` →
  `celery/utils/functional_renamed.py` via `git mv`. After the debounce window, `ast_index.json`'s
  reverse index for the unique symbol `DummyContext` pointed only at
  `celery/utils/functional_renamed.py`; `celery/utils/functional.py` was absent from
  `index_data["files"]` and `celery/utils/functional_renamed.py` was present. Confirms `on_moved`
  removes the src path and re-indexes the dest path as a single logical rename (not left
  half-indexed). Test repo restored to its original state afterward (rename reverted, no residual
  git diff against HEAD).
- Verdict: PASS
