# COGNIREPO-204 — Manual test suite

## TC-204-1: One-call timeline
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/dummy (medium's size made ad-hoc
  seeding slow; dummy's `.cognirepo/` was backed up before seeding and restored after).
- Prerequisites: story merged; seed: 2 agent sessions, 3 log_episode, 1 record_decision,
  1 record_error.
- What to do: call the shipped surface (get_timeline or bootstrap digest).
- Prompt: "What happened in this repo in the last 7 days? Use a single CogniRepo call."
- Expected results: all seeded items, chronological, kinds labeled; rollup readable and
  mentions the decision; exactly one tool call needed.
- Obtained results: `get_agent_bootstrap()`'s `recent_timeline` (5-entry cap) correctly
  surfaced the 5 most-recent of the 7 seeded items (the 2 older sessions fell outside the
  cap, as designed). Calling `data.memory.timeline.merge(since="30d", limit=100)` directly
  (the full query surface behind the digest) returned all 7 seeded entries, newest first,
  correctly kind-labeled (3 episode, 2 session, 1 decision, 1 error). `rollup()` over those 7:
  `{"total": 7, "counts": {"error": 1, "decision": 1, "episode": 3, "session": 2},
  "top_decisions": ["switch session storage to SQLite"], "top_errors": ["ConnectionError (x1)"]}`
  — names both the decision and the error as required. One call either way (bootstrap digest
  or a single `merge()` call — no 3-call stitch).
- Verdict: PASS
- Re-verified: 2026-08-12, same `cognirepo_test_repo/dummy` fixture (backup/restore
  repeated), same seed shape, identical result — 7/7 entries, correct kind counts,
  `rollup()` naming both the decision and the error; bootstrap digest cap (`merge(since=
  "7d", limit=5)`) also spot-checked, returned the 5 most-recent as designed.

## TC-204-2: Archive inclusion
- Test repo: `cognirepo_test_repo/TC-204-2` (dedicated scratch fixture, isolated
  `.cognirepo/` — not the shared `dummy` fixture, avoids polluting it with a synthetic
  30-event rotation).
- Prerequisites: episodic_max_events lowered to 20; 30 events logged (rotation happened).
- What to do: query with and without include_archived.
- Prompt: "Show the full timeline including archived history, then just the recent one."
- Expected results: archived events present only in the first; counts differ accordingly; no
  duplicate IDs (D02).
- Obtained results: `include_archived=False` returned 18 entries (live only);
  `include_archived=True` returned all 30 (live + archived). Checked all 30 episode `ref`
  values (the episodic `id` field) for uniqueness across the combined live+archive set:
  30 refs, 30 unique — zero duplicates, confirming D02's fix (`_next_event_id()`) holds under
  a real rotation triggered by this story's merge logic, not just the isolated D02 test suite.
- Verdict: PASS
- Re-verified: 2026-08-12, `cognirepo_test_repo/TC-204-2` (fresh `cognirepo setup`,
  `episodic_max_events` set to 20, 30 events logged), identical result — 18 live /
  30 live+archived (12 archived), 30/30 unique episode refs.
