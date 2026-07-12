# COGNIREPO-100 — EPIC: Reliability Gate (Phase 0) → v2.0.1

## Backstory
CogniRepo shipped a breaking v2.0.0 restructure (flat 14-package layout → 6-layer hierarchy;
commits 146627d, 6b0c83d, 45b0b41). A full evidence audit on 2026-07-11 (see
`COGNIREPO-100-Discovery.md` in this folder — REQUIRED READING for every story) confirmed the
four historical v1.1.0 P0 blockers are fixed and the pytest suite is green (1203 passed /
5 skipped), but found: a regression of the [1.1.3] manifest fix, an episodic-memory ID
collision, an uncommitted requirements.txt diff reverting CVE fixes, a file watcher with no
debounce/rename handling and orphan-node leakage, no graph.pkl corruption quarantine, 5+
layer-invariant upward imports, and widespread doc drift. This epic is the hard gate: no other
epic starts until it is signed off.

## Description
Fix every confirmed defect and hardening gap from the Phase 0 audit. Full plan with per-story
interface contracts and data flows: `docs/planning/00-audit-and-reliability.md`.
Stories: 101 (single-source manifest generation), 102 (watcher debounce/rename/batched saves),
103 (orphan cleanup + graph.pkl quarantine), 104 (verify-index dirty detection), 105
(layer-invariant cleanup), 106 (docs truth pass).
Defects: D01 (manifest regression hotfix — do FIRST), D02 (episodic ID collision), D03
(requirements.txt CVE revert — needs user decision).
Suggested order: D01 → D03 → D02 → 101 → 102 → 103 → 104 → 105 → 106.

## Acceptance criteria
1. manifest.json / glama.json / openai_tools.json each list exactly the 34 decorated tools,
   generated not hand-edited, with a CI drift test.
2. Watched repo: ≥5 writes to one file within 1 s → exactly one reindex; `git mv a.py b.py` →
   lookup_symbol resolves to b.py, zero a.py hits; deleting a symbol from a file leaves no
   orphan graph node.
3. `cognirepo verify-index` reports STALE/DIRTY on uncommitted source modifications.
4. Corrupt graph.pkl is quarantined to graph.pkl.corrupt-<ts>; doctor reports it.
5. Zero runtime upward imports from data/intelligence/core into interface (grep-verified).
6. requirements.txt restored to CVE-fixed pins (or user-accepted downgrade recorded on D03).
7. Docs truth pass merged (FEATURES §15/§16, README Future Plans headers, SECURITY.md,
   IMPROVEMENTS.md, cli/docs_index shim removed).

## Notes
- Version: 2.0.1. Base branch: development. Conventions: /skill.md.
- Epic sign-off requires all stories+defects signed off AND COGNIREPO-100-TEST_SUITE.md pass.
