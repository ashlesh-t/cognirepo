# COGNIREPO-701 — Reward-modulated salience decay

Epic: COGNIREPO-700 · Branch: story/COGNIREPO-701 · Base: development

## Backstory
`symbol_weights[sym]["hit_count"]` (`data/graph/behaviour_tracker.py`, incremented at line 354)
is a raw, ever-incrementing counter with zero decay — confirmed no time-based decay anywhere in
the file; the only decay-like mechanism (the EMA update on the separate `relevance_feedback`
field, line 357) is event-triggered, not time-based, and isn't read by any scoring path.
`last_hit` (line 355) is written but never read back — pure write-only telemetry. Consumer
`HybridRetriever._behaviour_score` (`intelligence/retrieval/hybrid.py:424-436`) log-normalizes
this same raw count with no recency weighting. Neuroscience parallel: reward-modulated STDP with
eligibility traces — a synaptic trace decays over seconds, consolidated only if reward arrives
while it's still positive (Izhikevich 2007; Frontiers 2015 three-factor learning rules review).
Evidence: `../../COGNIREPO-700-Discovery.md` §1.

## Description
Add a time-decayed salience signal per symbol — an eligibility-trace-inspired score where recent
hits are weighted heavier than old ones (exponential decay, configurable half-life) — that
`HybridRetriever._behaviour_score` consumes instead of, or blended with, raw `hit_count`. Gate via
`config.json` (mirrors COGNIREPO-202's `indexing.similarity_edges` pattern — explicit config
value always wins, sensible default otherwise). Actually put `last_hit` to use for the first time
in the codebase: the decay factor is computed from `now - last_hit` (or a small ring of recent
hit timestamps if a single `last_hit` proves too coarse — decide at Analyze/implementation time).
Preserve `hit_count` itself unchanged (other consumers may still want the raw count) — this is an
additive decayed-score field, not a replacement of the existing one, unless Analysis finds a
clean in-place migration is safe and simpler.

## Acceptance criteria
1. Two symbols with equal historical `hit_count`, one hit again this week and one untouched for
   6+ months, rank differently — the recent one scores higher.
2. Golden regression: for data where every hit's timestamp is "now" (fresh session), the decayed
   score matches today's (v2.2.0) `_behaviour_score` output within floating-point tolerance — zero
   behavior change for the common case.
3. Decay parameters (half-life or equivalent) are configurable via `config.json`, with a default
   that ships in `config.json`'s schema/example.
4. No regression on `interface/tools/benchmark.py`'s existing retrieval-quality measurement —
   report the before/after numbers in the PR.

## Risks / notes
- `last_hit` is single-valued (overwritten on every hit) — if decay needs hit *frequency* over a
  window rather than just recency-of-last-hit, this may need a small bounded history per symbol
  instead of a single timestamp. Resolve at Analyze; don't over-engineer if last_hit alone is
  sufficient to satisfy AC1.
- Must not change `hybrid.py`'s weight-sum invariant (`_load_weights()` validates weights sum to
  1.0, line 63) — a new signal type should slot into the existing `behaviour` weight slot, not
  add a new top-level weight, unless the story's Analyze step finds a strong reason otherwise.
