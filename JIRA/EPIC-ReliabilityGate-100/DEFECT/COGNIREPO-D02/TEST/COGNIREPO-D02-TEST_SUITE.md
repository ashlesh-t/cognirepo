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
- Obtained results:
- Verdict:
