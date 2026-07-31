# COGNIREPO-600 — EPIC: OSS growth / production polish (Phase 5) → v2.4.1

## Backstory
The claims must be as reliable as the code. Audit findings (2026-07-11): README's benchmark
story is internally inconsistent (4 repos at :18, 6 at :78, 4 at :98, while METRICS.md's
automated table covers 3), fastapi memory recall is published as 0% "under investigation",
METRICS.md still shows pre-[1.1.3] zeros, the support Discord isn't linked from README, the
contribution funnel has no good-first-issue on-ramp, and registry artifacts (glama.json,
openai_tools.json) were hand-drifted until COGNIREPO-101. Evidence:
`COGNIREPO-600-Discovery.md` (this folder). Plan: `docs/planning/05-oss-growth.md`.

## Description
Stories: 601 (benchmark re-run ≥2.2.0 across ≥6 repos + local fixture tier; reconcile
README/METRICS; root-cause fastapi recall), 602 (contribution funnel: good-first-issue set
seeded from audit leftovers, CONTRIBUTING.md funnel section linking DEVELOPER_GUIDE recipes,
issue templates), 603 (registry verification post-101 + Discord link + insights-report showcase
in README — showcase sub-part blocked on EPIC-300).
Order: 601 ∥ 602 ∥ 603 (independent). Requires COGNIREPO-101 merged; not the whole of EPIC-100.

## Acceptance criteria
1. Dated benchmark re-run in METRICS.md; all README repo counts agree with it.
2. No unexplained 0% metric remains.
3. ≥8 open `good first issue` issues, each Discovery-grounded; CONTRIBUTING links label+recipes.
4. glama.json/server.json/openai_tools.json verified generated at shipped version; mcp-name
   marker intact.
5. README: Discord link live; insights showcase (screenshot + paragraph) once EPIC-300 ships.

## Notes
Version 2.4.1 (escalate to 2.5.0 only if the fastapi fix changes product behavior). Opening
GitHub issues and README publishing are outward-facing — get explicit user go-ahead per action.
moby/kubernetes re-index runs are hours on the user's machine — schedule with them.
