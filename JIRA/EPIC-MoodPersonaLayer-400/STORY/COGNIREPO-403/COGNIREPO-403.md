# COGNIREPO-403 — "Caveman" economy persona

Epic: COGNIREPO-400 · Branch: story/COGNIREPO-403 · Base: development

## Backstory
THE novel idea of the phase: an output-side token reducer mirroring context_pack's input-side
reduction (README's headline value prop). Hard bar from README.md:91 "Honest limits": never
trade accuracy for compression — compression comes from STYLE, never content. Trigger: explicit
opt-in ONLY (record_user_preference("persona","caveman")); the QUICK classifier tier
(intelligence/orchestrator/classifier.py:24,301) may power a one-line SUGGESTION in the profile
payload after sustained QUICK-tier usage, never auto-enable (classifier scores retrieval
queries, not generations). Evidence: ../../COGNIREPO-400-Discovery.md §2, §5.

## Description
Ship as: (1) an output_contract string (~60 tokens) served in the profile/bootstrap payload ONLY
when active — telegraphic complete-information style: headline verdict first; minimal factual
lines; RETAIN all file:line refs, numbers, caveats; DROP preamble, hedging, restatement,
transitions. (2) Docs (USAGE.md + CLAUDE.md) with before/after example pairs, e.g.:
- OFF (~90 tok): "I looked into the failing test and it turns out the root cause is that the
  fixture creates the index before the config is patched, so the path resolver still points at
  the old directory. You can fix this by moving the monkeypatch above the fixture…"
- ON (~25 tok): "Root cause: fixture builds index before config patch → stale path. Fix: move
  monkeypatch above fixture, tests/test_x.py:42. Caveat: also used by test_y."
(3) The QUICK-usage suggestion hint (profile-side, one line, dismissible by preference).

## Acceptance criteria
1. output_contract present in payload iff persona active (test).
2. Contract text explicitly forbids omitting caveats/numbers/references.
3. Docs ship ≥3 before/after pairs with token counts.
4. Measured by COGNIREPO-404 before the epic can sign off.

## Risks / notes
- Non-Claude clients may ignore output_contract — acceptance measured on Claude Code;
  best-effort elsewhere.
