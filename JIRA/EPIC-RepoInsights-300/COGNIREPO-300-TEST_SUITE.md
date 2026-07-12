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
- Obtained results:
- Verdict:

## E2E-300-2: Empty-history honesty (crosses 301+302)
- Test repo: /home/ashlesh/my_works/cognirepo_test_repo/dummy
- Prerequisites: fresh init + index, zero episodic history.
- What to do: run `cognirepo insights`.
- Prompt: "Generate insights for this repo and tell me what it contains."
- Expected results: report generates; history-dependent sections read "no data recorded";
  nothing invented; git-derived sections still real.
- Obtained results:
- Verdict:
