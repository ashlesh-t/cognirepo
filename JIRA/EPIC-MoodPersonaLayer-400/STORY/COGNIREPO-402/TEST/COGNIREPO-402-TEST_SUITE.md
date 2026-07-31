# COGNIREPO-402 — Manual test suite

## TC-402-1: Opt-in lifecycle
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/easy
- Prerequisites: story merged; MCP connected.
- What to do: set persona=mentor → ask a question; set persona=banana (invalid); clear persona.
- Prompt: "Set my persona to mentor, then explain how retrieval caching works here."
- Expected results: mentor answer visibly deeper (episodic context included); invalid value
  rejected with the valid list; cleared ⇒ baseline behavior.
- Obtained results:
- Verdict:
