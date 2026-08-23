# COGNIREPO-401 — Manual test suite

## TC-401-1: Frustration detection changes behavior
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: story merged; MCP connected; fresh session.
- What to do: record_error("ImportError", ...) 3× within minutes; call get_user_profile.
- Prompt: "Check my profile — how am I doing this session, and what should you do differently?"
- Expected results: mood.state=frustrated; evidence cites the ImportError streak;
  suggested_adaptation is actionable; on a fresh repo the same call reports neutral.
- Obtained results: ran the record_error/get_user_profile mechanics directly (not via a live
  MCP session) on cognirepo_test_repo/medium/ansible: 3× `record_error("ImportError", ...)`
  then `get_user_profile()["mood"]` → `{"state": "frustrated", "evidence": ["ImportError: 3
  occurrences in the last 15m"], "suggested_adaptation": "verify against get_error_patterns
  before proposing fixes"}`. Same call on a fresh dummy repo (no errors seeded) →
  `{"state": "neutral", "evidence": [], "suggested_adaptation": ""}`. The live-agent leg (an
  actual reconnected Claude session reading mood off get_user_profile through MCP and changing
  its behavior accordingly) not re-run here — pending user's own session.
- Verdict: PASS (mechanics); live-agent leg pending user confirmation
