# COGNIREPO-402 — Manual test suite

## TC-402-1: Opt-in lifecycle
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy
- Prerequisites: story merged; MCP connected.
- What to do: set persona=mentor → ask a question; set persona=banana (invalid); clear persona.
- Prompt: "Set my persona to mentor, then explain how retrieval caching works here."
- Expected results: mentor answer visibly deeper (episodic context included); invalid value
  rejected with the valid list; cleared ⇒ baseline behavior.
- Obtained results: ran the record_user_preference/get_user_profile mechanics directly (not via a
  live MCP session): `record_user_preference("persona","mentor")` → `{"recorded": true}`,
  `get_user_profile()["active_persona"]=="mentor"` with the full behavior block surfaced.
  `record_user_preference("persona","banana")` → `{"recorded": false, "error": "unknown persona
  'banana' — valid: ['caveman', 'mentor', 'pair']"}`, and `active_persona` stayed `"mentor"`
  (invalid value did not clobber the existing one). Switching to `"pair"` afterward correctly
  updated `active_persona`. The live-agent leg (an actual reconnected Claude session visibly
  answering deeper under mentor vs. baseline) not re-run here — pending user's own session.
- Verdict: PASS (mechanics); live-agent leg pending user confirmation
