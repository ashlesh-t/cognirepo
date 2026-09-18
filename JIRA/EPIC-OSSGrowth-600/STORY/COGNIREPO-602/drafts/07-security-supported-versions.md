TITLE: SECURITY.md "Supported Versions" table still says 0.1.x

LABELS: good first issue, documentation

BODY:
## Context

`SECURITY.md`'s "Supported Versions" section reads:

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✓ Current |
| < 0.1.0 | ✗         |

The project is well past 0.1.x (check `version.yml` for the current version). Per the policy
text above the table ("Only the latest release receives security patches"), this table should
track the current release, not a version from very early in the project's history.

## Files involved

- `SECURITY.md` (Supported Versions section)

## What to do

1. Check the current version: `cat version.yml`.
2. Update the table to reflect the real policy — likely just `2.x.x ✓ Current` / `< 2.0.0 ✗`,
   but confirm with a maintainer in the PR if you're unsure how far back "supported" should
   extend (the policy text says "only the latest release," which argues for a single current-
   major-version row).

## Acceptance criteria

- [ ] Table reflects the actual current version
- [ ] No change to the policy text itself unless it's factually wrong too

## Recipe

None needed — verify against `version.yml`.
