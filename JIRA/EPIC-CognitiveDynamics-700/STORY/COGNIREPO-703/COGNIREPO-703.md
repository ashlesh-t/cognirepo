# COGNIREPO-703 — Confidence-calibrated tier classification

Epic: COGNIREPO-700 · Branch: story/COGNIREPO-703 · Base: development

## Backstory
`intelligence/orchestrator/classifier.py::_compute_score()` (lines 244-297) additively
accumulates a scalar from independent signals (reasoning keywords, lookup keywords, vague
referents, cross-entity count, context-dependency, token length, imperative+abstract combo — each
with a fixed weight, file:line detailed in Discovery §3), and `_score_to_tier()` (lines 300-307)
maps it onto fixed boundaries (`_TIER_QUICK=2.0`, `_TIER_STANDARD=4.0`, `_TIER_COMPLEX=9.0`, lines
92-94). This is structurally a bounded evidence-accumulation model — the same computational shape
as classic decision models where independent evidence sums until a threshold triggers a decision —
but only the final tier label survives; the margin at the threshold crossing (a 3.9 score is a
near-miss for STANDARD/COMPLEX; a 0.1 score is a decisive QUICK) is discarded today. Neuroscience
parallel: evidence accumulation to a bound in posterior parietal cortex/LIP (Gold & Shadlen 2007),
where confidence/reaction-time correlates with the margin at threshold-crossing. Evidence:
`../../COGNIREPO-700-Discovery.md` §3.

## Description
Add a `confidence` (or `margin_to_boundary`) field to `ClassifierResult`
(`classifier.py:116` dataclass) — computed from the final accumulated score and its distance to
the nearest tier boundary (both the one it crossed and the one above it, whichever framing Analyze
finds clearest). Purely additive: zero change to `_compute_score()`'s signal weights or
`_score_to_tier()`'s boundaries, zero change to which tier a query lands in. Document the
neuroscience framing briefly in the module (this file already carries the model-name-invariant
comment block — a natural home for a short note on why "margin" rather than raw score is the
exposed signal).

## Acceptance criteria
1. Tier assignment is byte-identical before and after this change for the full existing test
   corpus — golden regression, not just a spot check.
2. `confidence` is measurably lower for a near-boundary query (e.g. hand-constructed to score
   ~3.9, just under the 4.0 STANDARD/COMPLEX boundary) than for a decisively mid-tier query (e.g.
   score ~0.1, deep in QUICK) — unit-tested against concrete fixtures, not just "it exists."
3. `signals` dict output (already exposed for audit) is unchanged — this story adds one new field
   to `ClassifierResult`, it does not restructure existing output.
4. Model names remain nowhere in this change — this story touches only scoring/confidence logic,
   not model selection.

## Risks / notes
- Do not conflate this with fixing the model-name-invariant violations found elsewhere in
  `router.py`/`key_probes.py`/`model_adapters/*.py` during this epic's Discovery — those are a
  separate, out-of-scope defect (see epic notes).
- Keep the confidence formula simple and explainable (e.g. normalized distance to nearest
  boundary) — this is a diagnostic signal for downstream consumers (including story 704), not a
  new tunable that needs its own config surface.
