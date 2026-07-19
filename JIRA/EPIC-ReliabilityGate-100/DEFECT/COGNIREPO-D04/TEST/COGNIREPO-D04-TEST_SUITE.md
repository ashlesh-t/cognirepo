# COGNIREPO-D04 — Manual test suite

## TC-D04-1: Real store_memory call succeeds after fix
- Test repo: /home/ashlesh/my_works/cognirepo (this repo, isolated .cognirepo test fixture)
- Prerequisites: fix applied (store_memory call site matches real signature).
- What to do: construct a BehaviourTracker with a real store_fn=store_memory, drive 10
  record_query() calls, then inspect style["framing_hints"] / style["last_summarized"].
- Prompt: n/a — automated via tests/test_behaviour_tracker.py (direct call, no mock).
- Expected results: summarize_interaction_style() returns True; framing_hints non-empty;
  last_summarized set; no exception swallowed.
- Obtained results:
- Verdict:
