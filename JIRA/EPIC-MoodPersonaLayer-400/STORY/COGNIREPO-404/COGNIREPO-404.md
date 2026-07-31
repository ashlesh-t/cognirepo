# COGNIREPO-404 — Output-side measurement harness

Epic: COGNIREPO-400 · Branch: story/COGNIREPO-404 · Base: development

## Backstory
docs/METRICS.md measures INPUT-side reduction only (context_pack vs raw reads; automated tables
:118-152); interface/tools/benchmark.py compares retrieval payloads, not generations. The
economy persona's claim needs its OWN harness — explicitly not an extension assumption.
Evidence: ../../COGNIREPO-400-Discovery.md §3.

## Description
New scripts/persona_bench.py (dev script, NOT a shipped tool): ~20 fixed repo questions with
golden answers (reuse the benchmark golden-set pattern — tests/fixtures/benchmark_golden*.json,
cf. CHANGELOG.md:61); for each, capture a live agent response persona-on and persona-off; count
response tokens with tiktoken (same encoder as context_pack.py:56-57); score accuracy by
golden fact/keyword match; emit JSON + a markdown table. Ship gate: median reduction ≥ 40% AND
accuracy Δ ≤ 2 pp. Results land in docs/METRICS.md as a dated "Output-side (persona)
measurements" section. Requires a live Claude Code session or API key — documented as a manual
bench, NOT CI.

## Acceptance criteria
1. Harness runs end-to-end and emits the report.
2. Gate evaluated and stated; if missed, persona is documented as experimental WITH the real
   numbers (honesty over marketing).
3. METRICS.md section added with run date + methodology.

## Risks / notes
- Prompt set must avoid questions whose golden answer is inherently one-line (floor effects).
