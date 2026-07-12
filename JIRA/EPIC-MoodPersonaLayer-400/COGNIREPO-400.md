# COGNIREPO-400 — EPIC: Agentic mood / persona layer (Phase 3) → v2.3.0

## Backstory
User decision: a backend tone signal extending get_user_profile/framing_hints plus a LIGHT
persona layer — not a new subsystem. All raw mood inputs already persist in the behaviour store
(error streaks, query velocity, rewrite hit_counts, edit momentum). The flagship deliverable is
the "caveman" economy persona: output-side token reduction mirroring context_pack's input-side
reduction — a direct extension of the README headline metric, with a hard accuracy bar
(README "Honest limits": never trade accuracy for compression). Evidence:
`COGNIREPO-400-Discovery.md` (this folder). Plan: `docs/planning/03-agentic-mood-layer.md`.

## Description
Stories: 401 (derive_mood() in behaviour_tracker → mood block in get_user_profile +
get_agent_bootstrap; neutral-on-sparse-data; precedence rule: explicit user request > persona >
framing_hints), 402 (exactly 3 personas — mentor / pair / caveman — opt-in via existing
record_user_preference("persona", ...); no new tools), 403 (caveman spec: telegraphic
complete-information style, opt-in ONLY, QUICK-tier may suggest never auto-enable,
output_contract text served only when active, before/after examples shipped in docs), 404
(output-side measurement harness scripts/persona_bench.py — same prompt persona on/off, tiktoken
response counts, golden-answer accuracy gate: median reduction ≥40% AND accuracy Δ ≤ 2 pp).
Order: 401 → 402 → 403 → 404. Requires EPIC-200 signed off.

## Acceptance criteria
1. Profile/bootstrap payloads include mood {state, evidence, suggested_adaptation}; neutral +
   empty evidence on fresh repos.
2. Zero new MCP tools; zero manifest-token growth; zero new required calls.
3. No persona preference ⇒ behavior byte-identical to 2.2.0 (golden regression test).
4. Harness report shows ≥40% median response-token reduction with non-inferior accuracy; the
   numbers land in docs/METRICS.md as a dated "Output-side" section.
5. Every persona doc section names concrete behavior deltas — nothing decorative.

## Notes
Version 2.3.0. Model names must NOT appear anywhere in this layer (classifier.py invariant).
Check the UserPromptSubmit hook text for conflicts with the precedence rule (Discovery §6).
404 needs a live agent session — manual bench, not CI.
