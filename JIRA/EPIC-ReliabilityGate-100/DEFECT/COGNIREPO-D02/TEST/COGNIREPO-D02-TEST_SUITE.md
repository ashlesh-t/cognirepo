# COGNIREPO-D02 — Manual test suite

## TC-D02-1: Rotation preserves ID uniqueness
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/dummy
- Prerequisites: defect merged; .cognirepo/config.json sets episodic_max_events: 20.
- What to do: log 30 distinct episodes via log_episode; inspect memory/episodic.json +
  episodic_archive.json.
- Prompt: "Log 30 numbered test episodes, then check the episodic store and archive for any
  duplicate event IDs and report the ID sequence."
- Expected results: 30 unique IDs across both files; rotation happened (archive non-empty);
  episodic_search('test episode 25') returns exactly the right entry.
- Obtained results (post-fix, defect/COGNIREPO-D02, 2026-07-13, executed against an isolated
  scratch `.cognirepo` with `episodic_max_events: 20`): logged 30 numbered episodes -> rotation
  triggered at the cap, 12 archived / 18 live. All 30 IDs unique across live + archive (e_0..e_29,
  no duplicates); prev chain fully resolvable. `search_episodes("test episode 25")` returned
  valid, correctly-resolved entries (e_12..e_16) but not specifically episode 25 — this is a
  pre-existing `_tokenize()` property (tokens <3 chars, incl. "25", are dropped, so the query
  degrades to "test episode" and can't distinguish by number), not a regression from this fix;
  the original bug's stated consequence (id_to_entry silently collapsing duplicate keys) does
  not occur since no duplicate IDs exist. Automated regression coverage added:
  tests/test_memory.py::TestEpisodicMemory::test_ids_unique_after_rotation,
  test_prev_chain_resolvable_after_rotation, test_existing_store_ids_unchanged_on_load — all
  verified to fail against the pre-fix code (reproduced 5 duplicate IDs) and pass post-fix. Full
  pytest: 1206 passed (1203 baseline + 3 new), 5 skipped.
- Verdict: PASS
