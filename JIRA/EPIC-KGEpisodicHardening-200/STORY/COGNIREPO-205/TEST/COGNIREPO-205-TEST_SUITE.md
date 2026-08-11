# COGNIREPO-205 — Manual test suite

## TC-205-1: Deep history stays searchable
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/dummy
- Prerequisites: story merged; episodic_max_events: 20; log 30 events where event #1 has a
  unique keyword ("zanzibar").
- What to do: episodic_search("zanzibar") with and without include_archived.
- Prompt: "Search episodic memory for 'zanzibar', including archived history."
- Expected results: hit found with flag on; miss (or empty) with flag off; response marks it
  archived.
- Obtained results: `episodic_max_events` set to 20 in `dummy/.cognirepo/config.json`
  (backed up/restored around the test); logged 30 events, event #1 = "zanzibar migration
  notes and rollout plan" (rotated into `episodic_archive.json` — live count 18, archive
  count 12). `search_episodes("zanzibar", include_archived=False)` → 0 results.
  `search_episodes("zanzibar", include_archived=True)` → hit found (`e_0`, the seeded
  entry), tagged `{"archived": true}`.
- Verdict: PASS

## TC-205-2: System events land in the timeline
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy
- Prerequisites: story merged.
- What to do: run `cognirepo index-repo .`; then query the timeline/episodic log.
- Prompt: "What system/indexing events happened in this repo today?"
- Expected results: exactly one index_event episode with file/symbol counts metadata.
- Obtained results: ran `cognirepo index-repo . --no-watch` against
  `cognirepo_test_repo/easy/fastapi` (`.cognirepo/` backed up/restored around the test).
  Episodic log after the run contained exactly 1 entry with `metadata.type ==
  "index_event"`: `{"type": "index_event", "symbols": 7701, "files": 1180,
  "elapsed_s": 4.29}` — matches the run's own printed summary ("7,701 symbols across
  1,180 files").
- Verdict: PASS
