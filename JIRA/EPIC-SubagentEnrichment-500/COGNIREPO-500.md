# COGNIREPO-500 — EPIC: Sub-agent delegation as data enrichment (Phase 4) → v2.4.0

## Backstory
CogniRepo is a memory/retrieval layer, not an orchestrator: interface/tools/ is stateless, no
spawning machinery exists, and the audit registered NO disagreement with the enrichment-only
scope. The deliverable: context_pack learns to say "these hits fall into N structurally
independent groups (no shared import/call path in the graph) — here are their TODOs" so a
consuming Claude Code session can choose to delegate to subagents. Evidence:
`COGNIREPO-500-Discovery.md` (this folder). Plan: `docs/planning/04-subagent-delegation.md`.

## Description
Stories: 501 (independence grouping inside intelligence/retrieval/hybrid.py — union-find over
hit files via IMPORTS/CALLS/CALLED_BY/DEFINED_IN connectivity, hop cap ~3, emit component_id per
hit; gated on graph integrity from COGNIREPO-201 — no hints when orphan count is high), 502
(context_pack assembles conditional delegation_hints [{group, files, reason}] + ≤3 TODO/FIXME
lines per group greped from hit files at pack time; hints counted last against max_tokens and
dropped first on overflow; CLAUDE.md consumer guidance line).
Order: 501 → 502. Requires EPIC-200 signed off (specifically 201).

## Acceptance criteria
1. ≥2 disconnected hit groups ⇒ delegation_hints present; all-connected ⇒ key ABSENT (zero
   fixed token cost).
2. TODO/FIXME lines listed per group, ≤3 each, {file, line, text}.
3. Added output ≤ ~60 tokens for the two-group case (tiktoken-measured in test).
4. Hit ranking/scores/status byte-identical with grouping disabled (golden test).
5. CLAUDE.md documents consumption; docs/MCP_TOOLS.md context_pack section updated.

## Notes
Version 2.4.0. Zero manifest growth (output-only change). Main quality risk: sparse graphs
producing false "independent" signals — the 201 integrity gate + reason strings are the
mitigations; keep them.
