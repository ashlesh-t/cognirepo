# COGNIREPO-D04 — Manual test suite

## TC-D04-1: Real store_memory call succeeds after fix
- Test repo: /home/ashlesh/my_works/cognirepo (this repo, isolated .cognirepo test fixture)
- Prerequisites: fix applied (store_memory call site matches real signature).
- What to do: construct a BehaviourTracker with a real store_fn=store_memory, drive 10
  record_query() calls, then inspect style["framing_hints"] / style["last_summarized"].
- Prompt: n/a — automated via tests/test_behaviour_tracker.py (direct call, no mock).
- Expected results: summarize_interaction_style() returns True; framing_hints non-empty;
  last_summarized set; no exception swallowed.
- Obtained results: Fixed `data/graph/behaviour_tracker.py:543` — dropped the nonexistent
  `importance=0.8` kwarg. `test_summarize_interaction_style_direct_call` now injects
  `store_fn = Mock(spec=store_memory, return_value={"conflicts": []})` instead of a loosely
  mocked `Mock(return_value=None)` — a spec'd mock enforces the real signature and would have
  caught the original `TypeError` at test time. Ran with a real `BehaviourTracker(graph,
  store_fn=store_fn)`, drove 10 `record_query()` calls: `summarize_interaction_style()` returned
  `True`, `framing_hints` = "prefers concise responses; often asks 'how' questions; domain
  vocabulary: does, work, in, middleware, routing", `last_summarized` set to a real timestamp,
  `store_fn.assert_called_once()` passed. `venv/bin/python -m pytest
  tests/test_behaviour_tracker.py -q` — 23 passed.
- Verdict: PASS
