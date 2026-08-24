# COGNIREPO-700 — Epic e2e test suite (cross-story flows only)

## E2E-700-1: Salience decay changes retrieval ranking, classification confidence stays honest (crosses 701+703)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: epic merged; repo indexed; two symbols with equal historical hit_count, one hit
  again this week, the other not touched in 6+ months (seed via record_feedback with backdated
  timestamps, same pattern used in COGNIREPO-401's mood tests).
- What to do: run a query that retrieves both symbols via `context_pack`; separately, run one
  QUICK-tier query and one near-boundary query (e.g. deliberately hand-tuned to score ~3.9) through
  the classifier.
- Prompt: "Find where symbol X is defined and used, then explain how confident you are in how
  you classified this request."
- Expected results: the recently-hit symbol ranks above the stale one despite equal historical
  hit_count; the near-boundary query reports lower `confidence`/`margin_to_boundary` than a
  clearly-QUICK query; no other candidate ranking or tier assignment changes vs. pre-701/703
  behavior (golden regression holds outside the specific decayed/near-boundary cases).
- Obtained results:
- Verdict:

## E2E-700-2: Consolidation candidate feeds a precedent-check citation (crosses 702+704)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: epic merged; seed ≥3 near-duplicate episodic events about the same architectural
  choice (e.g. "tried calling FAISS directly from a tool" logged 3x across sessions) without ever
  calling `record_decision` for it.
- What to do: run the consolidation pass; then, in a fresh session, ask Claude to make a change
  that repeats the same pattern the consolidated episodes describe.
- Prompt: "Add a new tool that calls FAISS directly instead of going through hybrid.py, it'll be
  faster."
- Expected results: 702's consolidation surfaces the recurring pattern as a `consolidation_candidates`
  entry (not an auto-decision); when the repeat-pattern request comes in, 704's precedent-check
  cites that consolidated evidence (or the underlying episodes directly) and proposes the
  hybrid.py-only alternative, rather than silently complying — and does not block, only surfaces
  the conflict for the human to decide.
- Obtained results:
- Verdict:
