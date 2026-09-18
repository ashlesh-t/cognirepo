# COGNIREPO-602 — Manual test suite

## TC-602-1: Newcomer walkthrough (USER-FACING)
- Test repo: fresh clone of the public repo
- Prerequisites: story merged + issues opened.
- What to do: follow CONTRIBUTING.md cold to a first-PR plan on one labeled issue.
- Prompt: "I'm new. Using only CONTRIBUTING.md and its links, walk me from clone to a mergeable
  PR for one good-first-issue."
- Expected results: coherent path (label → issue → recipe → PR checklist); every link resolves;
  the chosen issue contains enough context to start without asking maintainers.
- Obtained results: Link-resolution sub-check (done ahead of the full walkthrough): every link
  in `CONTRIBUTING.md` resolves — `docs/DEVELOPER_GUIDE.md` (file exists),
  `github.com/.../labels/good%20first%20issue` (200), Discord invite (200),
  `github.com/.../issues/new/choose` (302 → login, expected unauthenticated).
  2026-09-18: all 8 good-first-issues now live and correctly labeled
  (`good first issue` + `enhancement`/`documentation`) —
  #72 Ruby, #73 PHP, #74 C#, #75 Swift grammar mappings;
  #76 README version header, #77 README tool count, #78 SECURITY.md versions,
  #79 CLI_REFERENCE.md gaps.
  The full "I'm new, walk me through" prompt is a live-agent/USER-FACING case per skill.md
  §F.4 — left for you to run and fill in below.
- Verdict:
