# Phase 3 — Agentic mood / persona layer → v2.3.0

**Epic:** COGNIREPO-400 (`JIRA/EPIC-MoodPersonaLayer-400/`). Evidence:
`JIRA/EPIC-MoodPersonaLayer-400/COGNIREPO-400-Discovery.md` (*D400 §n*).
**Depends on:** Phase 1 (error/timeline signals stable); independent of Phase 2.

## Context / Why

Per user decision: a backend tone signal extending `get_user_profile`/`framing_hints`
(`data/graph/behaviour_tracker.py:347-400`), with a light persona layer — not a new subsystem.
All raw signals already persist in the behaviour store (error counts, query velocity, rewrites,
edit momentum — D400 §1). The flagship piece is the **"caveman" economy persona**: an
output-side token reduction mirroring `context_pack`'s input-side reduction — a direct extension
of the README's headline metric. METRICS.md measures input-side only (D400 §3); an output-side
harness is a required story here, not an assumption.

## Scope

**In:** mood derivation into existing payloads; 3 named personas; the economy ("caveman")
persona spec + opt-in; output-side measurement harness with accuracy gate.
**Out:** new required tool calls; any default-behavior change for existing users (strict
opt-in); sentiment labels with no behavioral mapping (dropped per D400 §5); model-name-aware
logic anywhere outside `classifier.py`.

## Acceptance criteria (epic)

1. `get_user_profile()` (and `get_agent_bootstrap()`) include a `mood` block:
   `{state: "neutral"|"frustrated"|"flow", evidence: [...], suggested_adaptation: str}` —
   `neutral` with empty evidence on fresh repos (D400 §6).
2. Zero new MCP tools; zero new required calls; manifest token growth = 0.
3. Personas are opt-in via `record_user_preference("persona", <name>)`; absent preference ⇒
   behavior identical to 2.2.0 (regression-tested).
4. The economy persona demonstrably reduces response tokens ≥ 40% on the harness set with
   accuracy non-inferior to persona-off (README "Honest limits" bar — README.md:91).
5. Each persona's doc section states its concrete behavior deltas (retrieval depth, verbosity,
   tone) — no purely decorative attributes.

## Stories

### COGNIREPO-401 — Mood signal derivation
- **Context/Why:** D400 §1/§5 — signals exist; only kept signals that change behavior.
- **Files:** `data/graph/behaviour_tracker.py` (new `derive_mood()` reading `error_patterns`
  recency/streaks, `query_history` burst rate, `query_rewrites` hit_count deltas,
  `record_file_edit` momentum), surfaced in `get_user_profile` (`:347-400`) and
  `get_agent_bootstrap` (`mcp_server.py:1747`), tests in `tests/test_behaviour_tracker.py`.
- **Interface contract:** additive output key on two existing tools; schemas unchanged (inputs
  untouched) → 0 manifest tokens (AC2).
- **Data flow:** tool → tracker (existing singleton path) → in-memory computation over the
  behaviour store; no new persistence.
- **State/schema:** none (derived). Back-compat: additive key.
- **Dependencies:** Phase 1 signed off (record_error/timeline stable).
- **Test oracle:** AC1 — seed 3 same-type errors in 10 min → `state: "frustrated"` with the
  error streak in `evidence`; empty store → `neutral`. Precedence documented: explicit user
  request > persona > framing_hints (D400 §6).

### COGNIREPO-402 — Persona registry (3 personas)
- **Context/Why:** small named set per user decision; opt-in substrate already exists
  (`explicit_preferences`, D400 §4).
- **Personas (exactly 3):**
  - `mentor` — verbose: full framing, explanations, links to decisions/history (retrieval depth
    +1, includes episodic context by default).
  - `pair` — default-equivalent: current behavior, mood-aware phrasing only.
  - `caveman` — economy: see 403.
- **Files:** `data/graph/behaviour_tracker.py` (validate/normalize the `persona` preference
  key; expose `active_persona` in profile), `CLAUDE.md` (persona honor rules + the precedence
  line), `docs/USAGE.md`.
- **Interface contract:** none new — `record_user_preference("persona", "caveman")` and
  `get_user_profile().active_persona`. 0 manifest tokens.
- **Data flow:** preference write → behaviour store (existing `:402-410`) → profile read.
- **State/schema:** one reserved preference key; back-compat total (unknown keys already
  tolerated).
- **Dependencies:** 401.
- **Test oracle:** AC3 — no preference ⇒ profile equals pre-phase snapshot (golden-file test);
  invalid persona value → rejected with message listing valid names.

### COGNIREPO-403 — "Caveman" economy persona specification
- **Context/Why:** the one novel idea; mirrors input-side reduction on the output side.
- **Trigger:** explicit opt-in ONLY (`record_user_preference("persona", "caveman")`), per the
  gate rule. The QUICK classifier tier (`classifier.py:24,301`) may *suggest* enabling it (a
  one-line hint in the profile payload after ≥N QUICK-tier sessions), never auto-enable —
  classification runs on retrieval queries, not generations (D400 §2).
- **What it looks like (spec, shipped in docs + CLAUDE.md):** telegraphic, complete-information
  responses — headline verdict, then minimal factual lines; retains file:line refs, numbers,
  and caveats; drops preamble, hedging, restatement, and prose transitions. Example pair
  (shipped in docs):
  - OFF (~90 tokens): "I looked into the failing test and it turns out the root cause is that
    the fixture creates the index before the config is patched, so the path resolver still
    points at the old directory. You can fix this by moving the monkeypatch above the fixture
    instantiation in tests/test_x.py line 42…"
  - ON (~25 tokens): "Root cause: fixture builds index before config patch → stale path.
    Fix: move monkeypatch above fixture, tests/test_x.py:42. Caveat: also used by test_y."
  - Rule: **never omit a caveat, number, or reference to save tokens** — compression comes from
    style, not content (accuracy bar, README.md:91).
- **Files:** CLAUDE.md + `docs/USAGE.md` persona section; profile payload carries the persona's
  `output_contract` string so any MCP client (Claude/Gemini/Cursor) gets the same instruction.
- **Interface contract:** none new; the `output_contract` text (~60 tokens) is served only when
  the persona is active — cost borne only by opted-in users.
- **Dependencies:** 402.
- **Test oracle:** AC4 via 404's harness; plus static: `output_contract` present iff persona
  active.

### COGNIREPO-404 — Output-side measurement harness
- **Context/Why:** D400 §3 — METRICS.md and `interface/tools/benchmark.py` are input-side only;
  this is an explicit new harness, not an extension assumption.
- **Files:** new `scripts/persona_bench.py` (not a shipped tool): fixed prompt set (~20 repo
  questions with golden answers reusing the benchmark golden-set pattern —
  `tests/fixtures/benchmark_golden*.json`, CHANGELOG.md:61), runs each prompt against a live
  agent session persona-on and persona-off, counts response tokens (tiktoken, same encoder as
  `context_pack.py:56-57`), scores accuracy (golden keyword/fact match, as benchmark precision
  does), emits a JSON + markdown table for METRICS.md.
- **Interface contract:** dev-script only, zero product surface. Measurement definition:
  `reduction = 1 - tokens_on/tokens_off` per prompt; ship gate = median ≥ 40% AND accuracy
  (fact-match rate) non-inferior (Δ ≤ 2 pp).
- **Data flow:** script → prompts → (external agent invocation — documented as requiring a
  Claude Code session or API key; NOT run in CI) → token counts → report.
- **State/schema:** none.
- **Dependencies:** 403.
- **Test oracle:** AC4 — the harness report itself, checked into `docs/METRICS.md` as a new
  "Output-side (persona) measurements" section with the run date.

## Architecture-rule compliance

No new tools, no storage changes, no model names outside `classifier.py` (the persona layer
never selects models — D400 §2). CLAUDE.md changes are additive behavior guidance, not rule
amendments. Ground Rule 3: manifest growth 0; opt-in-only payload growth ~60 tokens for opted-in
users, bought back by the ≥40% output reduction target.

## Version bump

**2.3.0** (from 2.2.0) — additive opt-in feature; profile payload gains keys.

## Risks / open questions

- Mood inference noise on sparse data — mitigated by `neutral` default + evidence array (AC1);
  still expect tuning.
- Double-signal conflict with the existing UserPromptSubmit hook injecting the profile
  (D400 §6) — precedence rule must land in CLAUDE.md in 401, and the hook text be checked for
  contradiction.
- 404 needs a live agent to measure generation — cannot run in CI; it's a documented manual
  bench (user or maintainer runs it). If ≥40% is missed, the persona ships as experimental with
  measured numbers published — honesty over marketing.
- Risk that clients ignore `output_contract` — acceptance measured on Claude Code specifically;
  other clients best-effort.
