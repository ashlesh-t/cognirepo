# COMPLETED_TASKS — audit & roadmap generation progress

Resume file for the CogniRepo deep-audit / roadmap task. Any model can resume from here.
Plan: `~/.claude/plans/you-are-doing-a-linked-blossom.md`. Rule: Discovery.md files are
written BEFORE any planning/ticket file; no ticket may cite an ungrounded fact.

| Stage | What | Status |
|---|---|---|
| A | Phase 0 verification & reliability audit (evidence gathering) | DONE 2026-07-11 |
| B | Per-epic discovery reads (Phases 1–5 modules) | DONE 2026-07-11 |
| C | Write all 6 `JIRA/EPIC-*/COGNIREPO-*-Discovery.md` files | DONE 2026-07-11 |
| D | Write `docs/planning/README.md` + `00`–`05` phase docs | DONE 2026-07-11 |
| E | Write JIRA tree (epics, stories, defects, test suites, status.yml) | DONE 2026-07-11 — 6 epics, 23 stories, 3 defects, 77 files, tree validated |
| F | Write `skill.md`, final self-check, update this file | DONE 2026-07-11 |

## ALL STAGES COMPLETE — audit & roadmap generation finished 2026-07-11

Implementation has NOT started. To begin: read `skill.md` §B (resume protocol) → root
`JIRA/status.yml` → active epic COGNIREPO-100 → suggested order D01 → D03 (user decision) →
D02 → 101 → 102 → 103 → 104 → 105 → 106. The final self-check is in `docs/planning/README.md`.

## Stage A/B key verdicts (full evidence in the Discovery files)

- Full pytest at HEAD: **1203 passed, 5 skipped, 0 failed** (100 s).
- All 4 v1.1.0-QA P0 blockers: **fixed at HEAD** (file:line in 100-Discovery).
- Manifest drift: **regression** — `find_symbol_path` + `get_service_endpoints` missing from
  `_build_manifest()`/`manifest.json` (32 vs 34) and `glama.json`; [1.1.3] had fixed exactly these.
- `requirements.txt` uncommitted diff **reverts committed CVE fixes** (779b113, 6083b15) → recommend revert, needs user confirmation.
- file_watcher: no debounce, no `on_moved`, orphan graph nodes on modify.
- episodic `log_event` ID collision after rotation (`e_{len(data)}`).
- Docs drift: FEATURES §15/§16, README Future Plans (v0.3.0 headers), SECURITY.md (Snyk), IMPROVEMENTS.md (stale counts), openai_tools.json (13 tools), `openai_spec.py` stale `server/manifest.json` path.

## Epic milestones (post-implementation, per skill.md §F)

- **COGNIREPO-300 — RepoInsights** — signed off 2026-08-23, v2.2.0. Stories 301 (data
  collector), 302 (HTML generator + idempotent writer), 303 (CLI + MCP tool + docs-index
  carve-out) all signed off; epic e2e suite (generate→regenerate→retrieve loop,
  empty-history honesty) PASS.
- **COGNIREPO-400 — MoodPersonaLayer** — signed off 2026-08-24, v2.3.0. Stories 401 (mood
  signal derivation), 402 (persona registry), 403 (caveman economy persona — ships
  experimental, missed the strict accuracy-delta gate but in the safe direction), 404
  (output-side measurement harness, 57.3% median reduction) all signed off; defect
  COGNIREPO-400-D01 (persona clear, found via the epic's own e2e suite) signed off; epic
  e2e suite (mood+persona end-to-end shift, economy persona measurement gate) PASS.
