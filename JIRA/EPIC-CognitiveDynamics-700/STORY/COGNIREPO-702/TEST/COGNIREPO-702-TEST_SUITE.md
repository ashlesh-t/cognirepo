# COGNIREPO-702 — Manual test suite

## TC-702-1: Recurring topic produces a consolidation candidate
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: story merged; seed ≥3 near-duplicate episodic events about the same symbol/file
  across sessions, no `record_decision` ever called for that topic.
- What to do: trigger the consolidation pass.
- Prompt: "Check if there's a recurring pattern in what I've logged recently that should become a
  recorded decision."
- Expected results: one `consolidation_candidates` entry citing the specific episode ids as
  evidence, with a suggested decision draft; `record_decision` is NOT called automatically.
- Obtained results: Real end-to-end run against `cognirepo_test_repo/medium/celery` — seeded 3
  near-duplicate episodes ("worker keeps crashing on redis broker reconnect...") plus 2
  unrelated episodes via real `log_event()` calls, then called the actual `get_agent_bootstrap()`
  MCP tool. Output: `decision_nudge: "1 recurring topic(s) never promoted to a decision — see
  consolidation_candidates"`, `consolidation_candidates` has exactly one entry citing
  `["e_4", "e_5", "e_6"]` (the 3 real near-duplicates, correctly excluding the 2 unrelated
  episodes) with a `suggested_decision_draft`. `record_decision`/`log_event(type=decision)` not
  called — also verified by a dedicated unit test that patches `log_event` and asserts zero
  calls during the consolidation pass itself
  (`tests/test_consolidation.py::test_never_calls_record_decision_or_logs_a_decision`).
- Verdict: **PASS**

## TC-702-2: Sparse store stays honest
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/dummy
- Prerequisites: story merged; fresh init, zero/near-zero episodic history.
- What to do: trigger the consolidation pass.
- Prompt: "Check if there's a recurring pattern that should become a recorded decision."
- Expected results: empty `consolidation_candidates`, nothing invented.
- Obtained results: Real run against `cognirepo_test_repo/dummy` (genuinely empty/fresh
  episodic store) via the actual `get_agent_bootstrap()` MCP tool: `decision_nudge: None`,
  `consolidation_candidates` key **absent entirely** from the result (not an empty list) —
  matches this payload's existing "omitted when nothing to report" convention
  (`decision_nudge`/`child_services` follow the same pattern). Nothing fabricated; the gate
  didn't even fire since episode count stayed below the existing COGNIREPO-205 threshold of 5.
  Test-repo directory cleaned up afterward (no stray `.cognirepo/` left behind).
- Verdict: **PASS**
