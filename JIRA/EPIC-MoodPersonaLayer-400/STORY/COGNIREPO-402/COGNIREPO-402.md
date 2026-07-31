# COGNIREPO-402 — Persona registry (mentor / pair / caveman)

Epic: COGNIREPO-400 · Branch: story/COGNIREPO-402 · Base: development

## Backstory
Exactly 3 named personas (user decision: small set, opt-in, light layer). Opt-in substrate
already exists: record_user_preference / explicit_preferences
(data/graph/behaviour_tracker.py:402-415) — a reserved "persona" key means ZERO schema changes
and zero new tools. Evidence: ../../COGNIREPO-400-Discovery.md §4.

## Description
Personas and their CONCRETE behavior deltas (documented in docs/USAGE.md + CLAUDE.md):
- mentor: retrieval depth +1 (include episodic context by default), full explanations, links to
  related decisions/history.
- pair: current behavior + mood-aware phrasing only (the default-equivalent).
- caveman: economy output (spec in COGNIREPO-403).
Implementation: BehaviourTracker validates the persona preference value (reject unknown with the
valid list), exposes active_persona + that persona's behavior block in get_user_profile output.
No preference ⇒ payload identical to pre-phase (golden test).

## Acceptance criteria
1. record_user_preference("persona","mentor") ⇒ profile.active_persona="mentor" with its
   behavior block; invalid value rejected listing valid names.
2. No persona ⇒ golden-identical profile output.
3. Docs name each persona's deltas (retrieval depth, verbosity, tone) — nothing decorative.

## Risks / notes
- Depends on 401 (mood block ships first; personas reference it).
