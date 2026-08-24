# skill.md — How to execute the CogniRepo JIRA backlog (for Claude Code sessions)

This document makes any future Claude Code session self-sufficient for implementing the roadmap
in `JIRA/`. It describes the folder structure, the resume protocol, and the per-story execution
+ review loop. **These are instructions for the implementing session — read fully before
touching code.** Planning rationale lives in `docs/planning/`; evidence in each epic's
`COGNIREPO-<ID>-Discovery.md`.

---

## A. JIRA folder structure and ID scheme

```
JIRA/
  status.yml                                  # ROOT registry: all epics, states, active pointer
  EPIC-<MilestoneName>-<ID>/                  # e.g. EPIC-ReliabilityGate-100
    COGNIREPO-<ID>.md                         # epic: backstory, description, AC, notes
    COGNIREPO-<ID>-Discovery.md               # audit evidence, file:line grounded — REQUIRED READING
    COGNIREPO-<ID>-TEST_SUITE.md              # epic-level e2e suite: ONLY cross-story flows
    status.yml                                # per-epic state
    STORY/
      COGNIREPO-<StoryID>/
        COGNIREPO-<StoryID>.md                # story ticket (self-contained)
        COGNIREPO-<StoryID>_Subtask1.md       # OPTIONAL — create when splitting a story;
        COGNIREPO-<StoryID>_Subtask2.md       #   sub-tasks share the story's branch and PR
        TEST/
          COGNIREPO-<StoryID>-TEST_SUITE.md   # manual test suite (format in §F.4)
    DEFECT/
      COGNIREPO-<DefectID>/                   # same pattern as a story
        COGNIREPO-<DefectID>.md
        TEST/COGNIREPO-<DefectID>-TEST_SUITE.md
```

**ID scheme** (sequential, allocated once, recorded in status.yml):
- Epics: round hundreds — COGNIREPO-100, -200, -300, -400, -500, -600.
- Stories: increment within the epic — COGNIREPO-101, -102, …
- Defects: D-prefixed — COGNIREPO-D01, -D02, … (registered under their epic's status.yml).
- Sub-tasks are NOT separately numbered — they are `_SubtaskN.md` files under their story.
  New defects found during testing: take the next free D-number in the epic, create the folder,
  add it to the epic's status.yml.

Allocated epics: 100 ReliabilityGate (stories 101-106, defects D01-D03) · 200
KGEpisodicHardening (201-205) · 300 RepoInsights (301-303) · 400 MoodPersonaLayer (401-404) ·
500 SubagentEnrichment (501-502) · 600 OSSGrowth (601-603) · 700 CognitiveDynamics (701-704).

## B. status.yml — schema and RESUME protocol

Root `JIRA/status.yml`:
```yaml
project: cognirepo
active_epic: <COGNIREPO-ID or null>
epics:
  - id: COGNIREPO-100
    name: <milestone name>
    status: not-started | in-progress | in-testing | blocked | signed-off
    blocked_by: [<epic ids>]
```
Per-epic `EPIC-*/status.yml`:
```yaml
epic_id: COGNIREPO-100
status: not-started | in-progress | in-testing | blocked | signed-off
stories:
  - id: COGNIREPO-101
    status: not-started | in-progress | in-review | changes-requested | in-testing | signed-off
    branch: story/COGNIREPO-101
    pr: <url or null>
    test_status: not-run | pass | fail | blocked
defects:
  - id: COGNIREPO-D01
    status: <same enum>
    branch: defect/COGNIREPO-D01
    pr: <url or null>
    test_status: <same enum>
epic_test_suite_status: not-run | pass | fail | blocked
```

**Resume protocol — every new session, before anything else:**
1. Read root `JIRA/status.yml` → find `active_epic` (if null, pick the first epic whose
   `blocked_by` are all signed-off; set it active).
2. Read that epic's `status.yml` → resume any story that is `in-progress`/`in-review`/
   `changes-requested`; otherwise pick the next `not-started` story in ticket order (respect
   dependencies stated in the ticket).
3. Read the story ticket, its `_SubtaskN.md` files, and the epic's `Discovery.md`. Also read
   root `COMPLETED_TASKS.md` for cross-session notes.
4. Never repeat signed-off work. Update status.yml at EVERY state transition — it is the only
   shared memory between sessions. Keep root and per-epic files consistent (root epic status is
   the rollup of its stories).

## C. Branch convention

- `story/COGNIREPO-<ID>` (e.g. `story/COGNIREPO-101`) · `defect/COGNIREPO-<ID>` (e.g.
  `defect/COGNIREPO-D01`).
- **Base branch: `development`.** One branch per story/defect; sub-tasks share it. Rebase on
  development before opening the PR.

## D. Commit convention

Every commit message starts with the ticket ID:
```
COGNIREPO-101: <imperative summary>

<optional body after a blank line: what/why, notable tradeoffs>
```
Sub-task work also uses the parent story's ID. No commits without a ticket ID.

## E. PR convention

- Title: `COGNIREPO-<ID>: <story title>` · Target: `development` · One PR per story/defect
  (never per sub-task).
- Body: link the ticket path, list ACs with checkboxes, note the measured manifest-token delta
  when a tool schema changed, paste the test-suite verdicts.

## F. The per-story execution + review loop

Work like a company team — markdown tickets instead of Jira, Claude as the implementer, the
user as reviewer. For each story (defects follow the identical loop):

1. **Analyze.** Read the story .md, its sub-task files, and the epic's Discovery.md. Verify the
   cited file:line evidence still holds at your HEAD (code may have moved since the audit) —
   if it drifted, note the correction in the ticket before coding.
2. **Implement.** Work through sub-tasks in order (create `_SubtaskN.md` files first if you
   need to split the story). Respect CLAUDE.md invariants: tools stateless in
   `interface/tools/`, retrieval only via `intelligence/retrieval/hybrid.py`, model names only
   in `classifier.py`, storage under `.cognirepo/` (+ documented exceptions). Update docs
   whenever code changes make them stale (CLAUDE.md rule).
3. **DEV tests.** Write/update automated tests; run the full suite (`venv/bin/python -m pytest
   tests/ -q`). Green before proceeding.
4. **Manual TEST_SUITE.** Run `STORY/<id>/TEST/COGNIREPO-<ID>-TEST_SUITE.md`. Fill "Obtained
   results" + "Verdict" ONLY for cases you can genuinely execute yourself; leave user-facing/
   visual/live-agent cases empty — the user fills those from their own observation. Set
   `test_status` in status.yml.
5. **Commit & PR.** Commit (`COGNIREPO-<ID>: …`), push to the story branch, open a PR to
   `development` per §E.
6. **STOP.** Set story status `in-review` in status.yml. Ask the user to review the PR on
   GitHub. **Do not proceed. Do not start the next story.**
7. **GATE 1 — user says "reviewed" (or "yes"):** fetch the PR's review comments.
   - Comments exist → set `changes-requested` → resolve them → push → back to step 6 (ask for
     re-review).
   - No comments → proceed to Gate 2.
8. **GATE 2 — user says "GO AHEAD":** the story is signed off. Set story `signed-off`, update
   the epic rollup and root status.yml, then move to the next story per §B.

**Epic sign-off:** only after ALL its stories and defects are signed off AND the epic-level
`COGNIREPO-<ID>-TEST_SUITE.md` (cross-story e2e flows) passes. Then: mark the epic signed-off,
set root `active_epic` to the next unblocked epic, append the milestone to `COMPLETED_TASKS.md`,
and bump the version per the phase's planning doc (`version.yml` → `python
scripts/sync_version.py`; sequence: 2.0.1 → 2.1.0 → 2.2.0 → 2.3.0 → 2.4.0 → 2.4.1 → 2.5.0).

### F.4 TEST_SUITE.md case format (use for every new suite you write)
```
## TC-<id>: <name>
- Test repo: <one of /home/ashlesh/my_works/cognirepo_test_repo/{advanced,dummy,easy,medium,private-org} or the cognirepo repo itself>
- Prerequisites / setup steps:
- What to do:
- Prompt: "<the exact prompt a real user would give Claude>"
- Expected results:
- Obtained results:   (empty until executed; user fills user-facing cases)
- Verdict:            (PASS / FAIL / BLOCKED; empty until executed)
```

## G. Defect workflow

Anything found not working during testing (any gate, any suite) becomes a DEFECT ticket:
1. Allocate the next `COGNIREPO-D<nn>` in the epic; create
   `DEFECT/COGNIREPO-D<nn>/COGNIREPO-D<nn>.md` (backstory with reproduction + file:line,
   description/fix, AC) and its `TEST/COGNIREPO-D<nn>-TEST_SUITE.md` — write the test suite
   BEFORE fixing.
2. Register it in the epic's status.yml (`defects:` list) with branch `defect/COGNIREPO-D<nn>`.
3. Follow the full loop in §F — investigation and fix first; commit and PR only after the
   testing/fix work is finished; same two gates.
4. The parent story/epic cannot be signed off while its defects are open.

## H. Dogfooding (CLAUDE.md session rules still apply)

While implementing: use CogniRepo's own tools (`context_pack` before reading files,
`lookup_symbol` before assuming locations), and after every session `record_decision()` for
architectural choices, `log_episode()` for milestones, `record_error()` for errors hit — this
repo is the product; its memory of this work is part of the deliverable.
