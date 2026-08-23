# COGNIREPO-300 — Epic e2e test suite (cross-story flows only)

## E2E-300-1: Full generate → regenerate → retrieve loop (crosses 301+302+303)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/medium
- Prerequisites: epic merged; repo indexed; seeded history (decisions, episodes, ≥2 branches,
  ≥10 commits — the repo's real git history is fine).
- What to do: run `cognirepo insights`; open the HTML in a browser (light AND dark OS theme);
  make one commit + log one episode; run insights again; then query search_docs.
- Prompt: "Generate the insights report for this repo, then find what the report says about
  recent decisions using search_docs."
- Expected results: one file at .claude/insights/<repo>-insights.html both times (mtime
  advanced, updated_at changed, new episode visible); renders correctly in both themes with no
  network requests (check devtools); search_docs returns twin content; Claude's reply surfaces
  the path, not the HTML body.
- Obtained results: ran on cognirepo_test_repo/medium/ansible. First `cognirepo insights` wrote
  `.claude/insights/ansible-insights.html` (updated 06:57:29Z). Logged one episode + one empty
  commit on `devel`, reran insights: mtime advanced (06:57:29→06:58:17), updated_at changed, both
  new episode and new commit visible in Timeline/Branches. HTML is self-contained (no external
  URLs found via grep). `.cognirepo/docs/ansible-insights.md` twin picked up by
  `search_docs("E2E-300-1: epic e2e test run for COGNIREPO-300")` (score 0, exact-match hit),
  `.cognirepo/index/` internals stayed excluded (confirmed under TC-303-2). Light/dark visual
  render in an actual browser and the live Claude-prompt leg not re-run here — automated/CLI
  legs only; pending user's own visual + live-agent confirmation.
- Verdict: PASS (automated/CLI legs); visual + live-agent legs pending user confirmation

## E2E-300-2: Empty-history honesty (crosses 301+302)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/dummy
- Prerequisites: fresh init + index, zero episodic history.
- What to do: run `cognirepo insights`.
- Prompt: "Generate insights for this repo and tell me what it contains."
- Expected results: report generates; history-dependent sections read "no data recorded";
  nothing invented; git-derived sections still real.
- Obtained results: ran on cognirepo_test_repo/dummy (zero episodic history, and turns out not a
  git repo at all). `cognirepo insights` wrote `.claude/insights/dummy-insights.html` cleanly.
  Timeline/Decisions/Challenges/Branches all honestly read "no data recorded" — nothing
  fabricated; Index health shows the real symbols=0, files=0 from the actual index state, not an
  invented placeholder.
- Verdict: PASS
