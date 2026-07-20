# COGNIREPO-D09 — Manual test suite

## TC-D09-1: Live reproduction against cognirepo-ansible MCP server
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium/ansible
- Prerequisites: story/COGNIREPO-105 (with D04–D08 fixes) checked out and reinstalled into the
  venv actually backing the running `cognirepo-ansible` MCP server; encryption deps
  (`keyring`, `cryptography`) present.
- What to do: fire 10 diverse `retrieve_memory` queries in a single parallel tool-call batch to
  cross `_STYLE_SUMMARIZE_EVERY`, then inspect `.cognirepo/graph/behaviour.json` and run
  `retrieve_memory('interaction style')`.
- Prompt: "Run retrieve_memory('interaction style') and show me the stored profile summary."
- Expected results (pre-fix): `interaction_style.last_summarized` stays `null`,
  `query_patterns` stuck at the 50-entry cap, no auto-generated `source="interaction_style"`
  memory appears (only a manually-stored probe memory was retrievable).
- Obtained results (pre-fix): confirmed exactly this — `query_history` grew normally (48 → 58)
  but `last_summarized: null`, `query_patterns` length 50, no automatic interaction_style
  memory. Direct, single-threaded calls to `summarize_interaction_style()` in isolation
  succeeded every time, isolating the bug to concurrent `save()` calls specifically.
- Verdict (pre-fix): FAIL — confirms COGNIREPO-D09.

## TC-D09-2: Same reproduction after the fix
- What to do: same as TC-D09-1, applied after `_behaviour_lock()` +
  `_merge_from_disk()` landed in `data/graph/behaviour_tracker.py`.
- Expected results: `retrieve_memory('interaction style')` (even when the triggering queries
  were issued in parallel) surfaces a fresh, auto-generated `source="interaction_style"`
  memory; `last_summarized` is a real timestamp; `query_patterns` resets to `[]` (plus any
  genuinely-new queries appended after the reset).
- Obtained results: unit-level equivalent covered by
  `TestBehaviourTrackerConcurrentSave::test_concurrent_summarize_reset_is_not_reverted` and
  `::test_concurrent_instances_do_not_lose_query_history` in
  `tests/test_behaviour_tracker.py` — both simulate two independently-loaded
  `BehaviourTracker` instances racing on `save()` and assert neither the query_history entries
  nor the summarize reset are lost. `venv/bin/python -m pytest tests/test_behaviour_tracker.py
  -q` — 25 passed. Full suite: `venv/bin/python -m pytest tests/ -q` — 1253 passed, 5 skipped.
- Verdict: PASS
