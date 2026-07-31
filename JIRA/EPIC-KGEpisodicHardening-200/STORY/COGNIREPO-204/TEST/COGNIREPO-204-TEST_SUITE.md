# COGNIREPO-204 — Manual test suite

## TC-204-1: One-call timeline
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: story merged; seed: 2 agent sessions, 3 log_episode, 1 record_decision,
  1 record_error.
- What to do: call the shipped surface (get_timeline or bootstrap digest).
- Prompt: "What happened in this repo in the last 7 days? Use a single CogniRepo call."
- Expected results: all seeded items, chronological, kinds labeled; rollup readable and
  mentions the decision; exactly one tool call needed.
- Obtained results:
- Verdict:

## TC-204-2: Archive inclusion
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/dummy
- Prerequisites: episodic_max_events lowered to 20; 30 events logged (rotation happened).
- What to do: query with and without include_archived.
- Prompt: "Show the full timeline including archived history, then just the recent one."
- Expected results: archived events present only in the first; counts differ accordingly; no
  duplicate IDs (D02).
- Obtained results:
- Verdict:
