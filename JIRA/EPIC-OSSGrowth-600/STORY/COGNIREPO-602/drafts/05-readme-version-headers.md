TITLE: README "Future Plans" section still says "Now at v2.0.0"

LABELS: good first issue, documentation

BODY:
## Context

`README.md`'s "Future Plans" section (around line 615-617) opens with:

> Priorities drawn from the v0.3.0 benchmark findings and community feedback. Now at v2.0.0 —

The project is well past v2.0.0 now (check `version.yml` for the current version). This line
hasn't been updated across several releases.

## Files involved

- `README.md` (Future Plans section header, ~line 617)

## What to do

1. Check the current version: `cat version.yml` (or `cognirepo --version`).
2. Update the "Now at vX.Y.Z" line to the real current version.
3. Skim the rest of the Future Plans section (Short-term/Medium-term/Longer-term subsections) —
   flag (in the PR description, don't silently delete) any other item that reads like it's
   already done based on `CHANGELOG.md`, but leave the actual "done"/"partial" annotations to a
   maintainer to confirm unless you can verify the claim yourself against the live code.

## Acceptance criteria

- [ ] Version reference matches `version.yml`
- [ ] No other change to the section's content/structure

## Recipe

None needed — this is a doc-accuracy fix. Verify against `version.yml`, don't guess.
