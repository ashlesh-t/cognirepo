# COGNIREPO-102 — Manual test suite

## TC-102-1: Editor burst → single reindex
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: story merged to branch; cognirepo init + index-repo; `cognirepo watch` running
  with visible log output.
- What to do: script 5 writes to one .py file within 300 ms; watch the log.
- Prompt: "After I burst-save utils.py five times, check the watcher log and tell me how many
  re-index operations ran for it."
- Expected results: exactly one "[watcher] re-indexed" line for the file; one save cycle.
- Obtained results:
- Verdict:

## TC-102-2: Rename correctness
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: as TC-102-1; pick an indexed file with a known unique symbol.
- What to do: `git mv old_name.py new_name.py`; wait past the debounce window.
- Prompt: "Use lookup_symbol on <unique_symbol>. Which file does the index say it lives in?"
- Expected results: result points at new_name.py only; searching context_pack for the symbol
  never returns old_name.py.
- Obtained results:
- Verdict:
