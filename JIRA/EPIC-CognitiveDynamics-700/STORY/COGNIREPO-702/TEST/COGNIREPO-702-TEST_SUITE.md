# COGNIREPO-702 — Manual test suite

## TC-702-1: Recurring topic produces a consolidation candidate
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: story merged; seed ≥3 near-duplicate episodic events about the same symbol/file
  across sessions, no `record_decision` ever called for that topic.
- What to do: trigger the consolidation pass.
- Prompt: "Check if there's a recurring pattern in what I've logged recently that should become a
  recorded decision."
- Expected results: one `consolidation_candidates` entry citing the specific episode ids as
  evidence, with a suggested decision draft; `record_decision` is NOT called automatically.
- Obtained results:
- Verdict:

## TC-702-2: Sparse store stays honest
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/dummy
- Prerequisites: story merged; fresh init, zero/near-zero episodic history.
- What to do: trigger the consolidation pass.
- Prompt: "Check if there's a recurring pattern that should become a recorded decision."
- Expected results: empty `consolidation_candidates`, nothing invented.
- Obtained results:
- Verdict:
