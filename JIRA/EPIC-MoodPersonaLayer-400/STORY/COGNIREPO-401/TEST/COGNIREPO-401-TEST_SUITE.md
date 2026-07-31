# COGNIREPO-401 — Manual test suite

## TC-401-1: Frustration detection changes behavior
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: story merged; MCP connected; fresh session.
- What to do: record_error("ImportError", ...) 3× within minutes; call get_user_profile.
- Prompt: "Check my profile — how am I doing this session, and what should you do differently?"
- Expected results: mood.state=frustrated; evidence cites the ImportError streak;
  suggested_adaptation is actionable; on a fresh repo the same call reports neutral.
- Obtained results:
- Verdict:
