# COGNIREPO-602 — Manual test suite

## TC-602-1: Newcomer walkthrough (USER-FACING)
- Test repo: fresh clone of the public repo
- Prerequisites: story merged + issues opened.
- What to do: follow CONTRIBUTING.md cold to a first-PR plan on one labeled issue.
- Prompt: "I'm new. Using only CONTRIBUTING.md and its links, walk me from clone to a mergeable
  PR for one good-first-issue."
- Expected results: coherent path (label → issue → recipe → PR checklist); every link resolves;
  the chosen issue contains enough context to start without asking maintainers.
- Obtained results: Partial (mechanical) check done ahead of the full walkthrough — every link
  in `CONTRIBUTING.md` resolves: `docs/DEVELOPER_GUIDE.md` (file exists),
  `github.com/.../labels/good%20first%20issue` (200, label exists on the repo already), Discord
  invite (200), `github.com/.../issues/new/choose` (302 → login, expected unauthenticated). The
  full newcomer-walkthrough prompt itself is a live-agent/USER-FACING case per skill.md §F.4 —
  needs the 8 drafted issues actually opened first (pending your go-ahead, per this story's
  outward-facing constraint), then your own run-through.
- Verdict: (partial — link-resolution sub-check PASS; full walkthrough pending issues going live)
