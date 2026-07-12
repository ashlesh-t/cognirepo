# COGNIREPO-205 — Manual test suite

## TC-205-1: Deep history stays searchable
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/dummy
- Prerequisites: story merged; episodic_max_events: 20; log 30 events where event #1 has a
  unique keyword ("zanzibar").
- What to do: episodic_search("zanzibar") with and without include_archived.
- Prompt: "Search episodic memory for 'zanzibar', including archived history."
- Expected results: hit found with flag on; miss (or empty) with flag off; response marks it
  archived.
- Obtained results:
- Verdict:

## TC-205-2: System events land in the timeline
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy
- Prerequisites: story merged.
- What to do: run `cognirepo index-repo .`; then query the timeline/episodic log.
- Prompt: "What system/indexing events happened in this repo today?"
- Expected results: exactly one index_event episode with file/symbol counts metadata.
- Obtained results:
- Verdict:
