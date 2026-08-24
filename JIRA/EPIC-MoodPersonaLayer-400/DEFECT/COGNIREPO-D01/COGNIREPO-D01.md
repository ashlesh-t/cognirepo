# COGNIREPO-D01 — no way to clear a persona once set

Epic: COGNIREPO-400 · Branch: defect/COGNIREPO-400-D01 · Base: development

## Backstory
Found running `COGNIREPO-400-TEST_SUITE.md` E2E-400-1 step 4 ("clear preference, confirm
reversion") — the epic's own e2e suite assumes clearing is possible, but no story (401-404)
implemented it. `BehaviourTracker.record_user_preference()` (`data/graph/behaviour_tracker.py`)
validates `key == "persona"` values only against `_PERSONAS` (`mentor`/`pair`/`caveman`) and
rejects anything else — including `""` and `"none"`, both tried and rejected (verified at HEAD):
```
record_user_preference("persona", "")     -> {"recorded": false, "error": "unknown persona '' — valid: [...]"}
record_user_preference("persona", "none") -> {"recorded": false, "error": "unknown persona 'none' — valid: [...]"}
```
Once set, `active_persona` is permanently stuck at the last valid value — there is no delete
path anywhere in `user_preferences` generally, and no persona-specific escape hatch either.
This contradicts the epic's own "opt-in only" framing (CLAUDE.md, docs/USAGE.md): opt-in
implies the ability to opt back out.

## Description / fix
Add a reserved clear value for the `persona` key — `record_user_preference("persona", "none")`
(case-insensitive) removes the `persona` entry from `user_preferences` entirely (not stored as
a fourth "persona value", genuinely absent) rather than being rejected. `get_user_profile()`
then omits `active_persona`/`persona_behavior`/`output_contract` exactly as it does when no
persona was ever set (COGNIREPO-402 AC2's golden-identical behavior already covers this case —
no change needed there, just reaching it via clearing instead of never-setting).

## Acceptance criteria
1. `record_user_preference("persona", "none")` returns `{"recorded": true, "cleared": true}` (or
   equivalent) and removes the persona preference.
2. After clearing, `get_user_profile()` omits `active_persona`/`persona_behavior`/
   `output_contract` — byte-identical to the never-set case (reuses the existing COGNIREPO-402
   golden-regression assertion).
3. Clearing when no persona was ever set is a no-op, not an error.
4. `"none"` remains rejected as an actual *persona value* to switch to (it only means "clear") —
   `_PERSONAS` itself must NOT gain a 4th entry named "none".

## Risks / notes
- Keep this scoped to the `persona` key only — do not build a generic preference-delete
  mechanism for this defect; that's a larger surface than what's actually broken.
- Blocks COGNIREPO-400 sign-off per `skill.md` §G.4.
