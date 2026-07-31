# COGNIREPO-301 — Manual test suite

## TC-301-1: Model truthfulness
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: story merged; seeded: 1 record_decision, 1 record_error, ≥2 branches.
- What to do: run the collector from a REPL/pytest fixture; inspect the model.
- Prompt: "Run the insights collector on this repo and show me the raw model. Verify each
  decision/commit reference actually exists."
- Expected results: every ref resolves (episode ID in episodic.json, hash in git log); counts
  match seeds; no fabricated entries.
- Obtained results:
- Verdict:
