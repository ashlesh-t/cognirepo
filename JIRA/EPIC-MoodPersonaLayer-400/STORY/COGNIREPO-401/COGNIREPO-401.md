# COGNIREPO-401 — Mood signal derivation

Epic: COGNIREPO-400 · Branch: story/COGNIREPO-401 · Base: development

## Backstory
All mood inputs already persist in the behaviour store (data/graph/behaviour_tracker.py):
error_patterns w/ counts+last_seen (:314, :452-481), query_history timestamps (:159),
query_rewrites hit_counts (:417-448), file-edit momentum (:270). get_user_profile (:347-400)
already builds framing_hints and is the payload agents apply per CLAUDE.md. Signals were
filtered for "changes what Claude DOES": error streak (kept), query-velocity burst (kept,
experimental), momentum (kept), sentiment labels (dropped — decorative). Evidence:
../../COGNIREPO-400-Discovery.md §1, §5, §6.

## Description
BehaviourTracker.derive_mood() → {state: neutral|frustrated|flow, evidence: [str],
suggested_adaptation: str}. Heuristics (initial, tune later): frustrated = ≥3 same-type errors
within 15 min OR rewrite hit_count rising this session; flow = sustained edits + queries with 0
new errors over ≥20 min; else neutral. Sparse data ⇒ neutral + empty evidence (mirror the "no
profile yet" fallback :384). Surface as an additive `mood` key in get_user_profile AND
get_agent_bootstrap outputs (input schemas untouched — 0 manifest tokens, 0 new calls). Document
precedence in CLAUDE.md: explicit user request > persona > framing_hints/mood. CHECK the
UserPromptSubmit hook text for contradictions with that rule.

## Acceptance criteria
1. Seed 3 same-type errors in 10 min ⇒ frustrated with the streak in evidence.
2. Empty store ⇒ neutral, empty evidence.
3. Profile/bootstrap outputs otherwise byte-identical (golden test).
4. suggested_adaptation is an action ("verify against get_error_patterns before proposing
   fixes"), never a tone adjective alone.

## Risks / notes
- Session boundary: derive within the current session window (last N minutes), not all-time
  counts — all-time errors would pin mood permanently.

## Analyze correction (line drift vs Discovery, verified at implementation HEAD)
Discovery §1 line numbers were cited against `146627d` (v2.0.0); functions moved but are
unchanged in shape: `record_error` now :406, `get_error_patterns` :544, `record_query` :251,
`record_query_rewrite`/`get_query_rewrites` :509-540, `record_file_edit` :362, `get_hot_symbols`
:577-594, `get_user_profile` :437-484. `query_rewrites[].hit_count` is initialized to 0 in
`record_query_rewrite` but nothing in the current codebase increments it despite the docstring
claim ("incremented each time a matching query is seen") — pre-existing gap, out of scope for
this story; derive_mood() reads whatever value is there.
