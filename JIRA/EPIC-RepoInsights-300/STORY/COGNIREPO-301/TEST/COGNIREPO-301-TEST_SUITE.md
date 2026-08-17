# COGNIREPO-301 — Manual test suite

## TC-301-1: Real decisions/errors/timeline surfaced with real refs
- Test repo: `/home/ashlesh/my_works/cognirepo` (this repo's own `.cognirepo/`, read-only —
  no seeding needed, it already has real recorded decisions/episodes from prior sprints).
- Prerequisites / setup steps: none — read-only call against the live store.
- What to do: call `intelligence.orchestrator.insights_collector.collect(repo_root, since="90d")`
  directly (no MCP surface yet — this story ships the collector only).
- Prompt: "Aggregate what's happened in this repo over the last 90 days — decisions, errors,
  timeline — without inventing anything."
- Expected results: `decisions`/`timeline` sections `status: "ok"` with real episode ids as
  `ref`; `errors` section `status: "no_data"` (none recorded in the 90d window) rather than a
  fabricated entry.
- Obtained results: `decisions.items[0].ref == "e_0"`, summary "Roadmap v2.0.1→2.4.1 planned
  as 6 independent JIRA epics…" — matches the real COGNIREPO-100 decision episode.
  `timeline.rollup == {"total": 59, "counts": {"episode": 9, "session": 49, "decision": 1},
  "top_decisions": [...], "top_errors": []}`. `errors.status == "no_data"`, `items == []`
  (correct — no recorded errors in-window; not invented).
- Verdict: PASS

## TC-301-2: Git-derived sections are real regardless of `.cognirepo` state
- Test repo: `/home/ashlesh/my_works/cognirepo` (real git history) and
  `/home/ashlesh/my_works/cognirepo_test_repo/dummy` (fixture with an empty/no episodic data
  and no `.git` at all — worst case for AC2).
- Prerequisites / setup steps: none.
- What to do: call `collect()` against both repos; compare `branches`/`commits_by_week`.
- Prompt: "Show me this repo's branches and weekly commit activity for the last 90 days."
- Expected results: on the real repo, `branches`/`commits_by_week` populated with real commit
  hashes/dates and correct ahead/behind vs. default; on the non-git fixture, both sections
  report `status: "no_data"` (true state, not fabricated) while `.cognirepo`-derived sections
  (decisions/errors/timeline/hot_symbols) also correctly report `no_data` on the empty fixture.
- Obtained results: on `cognirepo` — `branches.items` includes
  `{"name": "chore/COGNIREPO-106-signoff", "last_commit": {"hash": "b0979bb8...",
  "date": "2026-07-21T00:29:43+05:30", "message": "COGNIREPO-100: sign off COGNIREPO-106
  (PR #41 merged, CI green)"}, "ahead": 80, "behind": 0, "is_default": false}` — real hash,
  correct ahead-count vs. default branch; `commits_by_week.weeks` bucketed by ISO week
  (e.g. `{"week": "2026-W24", "commits": 3, "added": 28113, "removed": 12519}`), all real
  diff stats. On `cognirepo_test_repo/dummy` (no `.git`, empty episodic store) — every
  section returned `status: "no_data"` except `index_health` (`status: "ok"`, `symbols: 0,
  files: 0` — the ast_index.json file exists and was read successfully, it's just empty;
  correctly reflects real on-disk state, not fabricated content).
- Verdict: PASS

## TC-301-3: `list_branches()` ahead/behind correctness (unit-level, automated)
- Test repo: synthetic (pytest `tmp_path` git repo — see
  `tests/test_git_utils_list_branches.py::test_ahead_behind_against_default_branch`).
- Prerequisites / setup steps: none — covered by the automated suite; listed here per §F.4
  for traceability since it directly backs AC1's "real refs" requirement for branches.
- What to do: `pytest tests/test_git_utils_list_branches.py -q`.
- Prompt: n/a (automated).
- Expected results: default branch shows `ahead=0, behind=0`; a feature branch 2 commits
  ahead shows `ahead=2, behind=0`; `last_commit.message` matches the most recent commit.
- Obtained results: PASS — `venv/bin/python -m pytest tests/test_git_utils_list_branches.py
  -q` → 2 passed.
- Verdict: PASS
