# COGNIREPO-700 — EPIC: Cognitive Dynamics (Phase 5) → v2.5.0

## Backstory
Originated from a discussion exploring whether CogniRepo could have something like
consciousness. Narrowed through research to what's actually buildable: a quantum/qubit substrate
was proposed and rejected (physically unsupported — decoherence timescales are ~9 orders of
magnitude too fast for neural-speed processing; see Discovery §0). What survived is three
mainstream, well-cited neuroscience mechanisms that map onto real gaps in this codebase — reward-
modulated salience decay, episodic-to-semantic consolidation, and confidence-calibrated decision
classification — plus a fourth, separately-motivated idea folded in at the user's request: a
grounded precedent-check that makes CogniRepo push back on instructions that contradict recorded
decisions, defects, or invariants, instead of silently complying. Evidence:
`COGNIREPO-700-Discovery.md` (this folder). Plan: `docs/planning/06-cognitive-dynamics.md`.

## Description
Stories: 701 (time-decayed, eligibility-trace-inspired salience for `symbol_weights`, consumed by
`HybridRetriever._behaviour_score`; config-gated; golden regression for fresh-data behavior), 702
(episodic-to-semantic consolidation pass — clusters recurring episodic events via existing
BM25/embedding similarity, surfaces `consolidation_candidates` with a suggested `record_decision`
draft; never auto-writes decisions), 703 (additive `confidence`/`margin_to_boundary` field on
`ClassifierResult`, zero change to tier assignment itself), 704 (precedent-check: surface a
conflict with a recorded decision/defect/invariant plus a concrete alternative before complying,
never auto-block, always defer to the human's final call — implementation shape decided at its
own Analyze step).
Order: 701 → 702 → 703 → 704. No hard dependency on any other epic — `blocked_by: []`.

## Acceptance criteria
1. 701: a symbol hit consistently this week outranks one hit equally often 6 months ago (equal
   raw hit_count); with all hits at "now," decayed score matches today's (2.2.0) behavior exactly
   — zero regression on fresh data.
2. 702: ≥3 near-duplicate episodic events on the same symbol/file within a window produce a
   `consolidation_candidates` entry with evidence citations (episode ids); never calls
   `record_decision` automatically; sparse/fresh store ⇒ empty candidates, nothing fabricated.
3. 703: tier assignment is byte-identical pre/post change (purely additive field); `confidence`
   is measurably lower near a boundary than mid-tier, unit-tested on concrete score fixtures.
4. 704: given a request that contradicts a specific recorded decision or a CLAUDE.md invariant,
   surfaces the conflict with a citation and a concrete alternative before implementing; given an
   ordinary request with no relevant precedent, zero friction (no false positives); validated
   against the live model-name-invariant violations found in this epic's own Discovery
   (`router.py`, `key_probes.py`, `model_adapters/*.py`) as a seed test case.
5. Every story's docs updated per CLAUDE.md's "update docs when code changes make them stale"
   rule; manifest-token deltas measured and reported in each PR, per `skill.md` §E.

## Notes
Version 2.5.0 (first bump beyond the 2.0.1→2.4.1 sequence already used through epic 600).
Citations live in `COGNIREPO-700-Discovery.md` only — not README (matches how every other epic's
research/audit evidence is kept out of user-facing docs). A 5th story (amygdala-inspired fast/
slow error-triage) was considered and dropped — see Discovery §5. A live invariant violation
(model names outside `classifier.py`) was found during this epic's audit but is NOT part of its
scope — flag for a separate defect ticket under whichever epic/session picks it up.
