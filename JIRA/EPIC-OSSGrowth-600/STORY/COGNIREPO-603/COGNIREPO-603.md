# COGNIREPO-603 — Registry verification + Discord link + insights showcase

Epic: COGNIREPO-600 · Branch: story/COGNIREPO-603 · Base: development
**Outward-facing README changes: user reviews before merge (standard Gate 1 covers this).**

## Backstory
Registry state at audit: README.md:3 mcp-name marker present; server.json current at 2.0.0
(synced by scripts/sync_version.py); glama.json + openai_tools.json were hand-drifted until
COGNIREPO-101 made them generated. The support Discord
(discord.com/channels/1488386981917360289/1488387271190380636) is NOT linked from README. The
EPIC-300 insights HTML is a natural README showcase. Evidence:
../../COGNIREPO-600-Discovery.md §2, §4.

## Description
(1) Verify all registry artifacts are generated-and-current at the shipped version (run the
COGNIREPO-101 drift test; check Glama listing reflects 34 tools post-D01). (2) README: add
Community section with the Discord link. (3) Showcase sub-task (BLOCKED until EPIC-300 ships):
generate the insights report on this repo, capture light+dark screenshots to docs/assets/, add a
"What CogniRepo can tell you about your repo" README section. Ship (1)+(2) without waiting on
(3).

## Acceptance criteria
1. Drift test green at release; server.json/version.yml/README tool counts agree.
2. Discord link live in README and resolves.
3. (post-EPIC-300) Showcase section with real screenshots — no mockups.

## Risks / notes
- Screenshots must come from a real generated report (honesty bar).
