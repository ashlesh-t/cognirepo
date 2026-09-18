# COGNIREPO-600 — Epic e2e test suite (cross-story flows only)

## E2E-600-1: Claims audit passes cold (crosses 601+603)
- Test repo: /home/ashlesh/my_works/cognirepo (this repo)
- Prerequisites: epic merged and published to the README on GitHub.
- What to do: as a skeptical newcomer, read README top-to-bottom against METRICS.md and the
  registry files; click every link.
- Prompt: "Read README.md and docs/METRICS.md. List every quantitative claim and check each one
  is internally consistent and sourced to a dated run. Flag anything that contradicts."
- Expected results: zero contradictions flagged; Discord link resolves; benchmark repo counts
  identical everywhere; fastapi row explained.
- Obtained results: Read README.md + docs/METRICS.md end to end (2026-09-18, post-603) as a
  skeptical audit, not a live-agent narrative (mechanical, not user-facing per skill.md §F.4).
  - Tool count: 35 everywhere (README:18/:56/:260, `docs/MCP_TOOLS.md` header) — verified
    against `_REGISTERED_TOOLS`, pinned by regression tests (`test_readme_tool_count_matches_
    registry`, `test_mcp_tools_md_header_count_matches_registry`).
  - Repo counts: the automated 4-repo table (flask/fastapi/celery/ansible, README:96-113,
    dated 2026-09-17) and the separate 6-repo 30-prompt live-agent table (README:78-89) are
    each internally consistent and clearly labeled as distinct methodologies — no false
    equivalence, matching the audit's original finding that this WAS silently conflated
    pre-story.
  - fastapi row: explicitly explained — `docs/METRICS.md:138` states the old "0% — empty
    vector DB" was a stale/transient artifact, not reproducible on re-run (now 100%). No
    unexplained 0% remains anywhere in either doc.
  - Links: Discord (200), good-first-issue label (200), issues/new/choose (302 → login,
    expected unauthenticated), docs/ARCHITECTURE.md GitHub blob link (200).
  - Real-world evidence beyond my own check: a genuine external contributor (PR #81) read the
    contribution funnel material, correctly picked up good-first-issue #77, and submitted a
    correct, verified, mergeable first PR — direct validation that the funnel this epic built
    (CONTRIBUTING.md, issue templates, labeled issues) works for a real newcomer, not just in
    simulation.
- Verdict: **PASS**

## E2E-600-2: Contributor cold-start (crosses 602)
- Test repo: /home/ashlesh/my_works/cognirepo (fresh clone)
- Prerequisites: 602 merged; issues opened.
- What to do: follow CONTRIBUTING.md from a fresh clone to a first PR on a good-first-issue.
- Prompt: "I want to contribute to CogniRepo. Using only CONTRIBUTING.md and what it links,
  pick a good first issue and tell me the exact steps to a mergeable PR."
- Expected results: a coherent path exists (label → issue → DEVELOPER_GUIDE recipe → PR
  checklist) with no dead links or missing sections.
- Obtained results: This happened for real during this epic's own work, which is stronger
  evidence than a simulated walkthrough — GitHub contributor Abhishek Kallolimath found
  good-first-issue #77 (README MCP tool count), correctly verified the real count via
  `@mcp.tool()` in `interface/server/mcp_server.py` per the issue's own instructions, and
  opened [PR #81](https://github.com/ashlesh-t/cognirepo/pull/81) — a correct, complete,
  appropriately-scoped fix, merged.
  One real gap surfaced by this live run: CONTRIBUTING.md never stated PRs should target
  `development` (not `main`) — not his fault, an actual gap in what this story shipped. Filed
  and fixed immediately as [PR #82](https://github.com/ashlesh-t/cognirepo/pull/82) (merged),
  and he retargeted his PR without friction once told. Link-resolution and section-completeness
  otherwise verified mechanically in TC-602-1 (`CONTRIBUTING.md`, issue templates, all 8 issues
  live and correctly labeled).
- Verdict: **PASS** — with one real gap found via live use and fixed same-day (PR #82); the
  funnel itself worked end-to-end for a genuine external contributor.
