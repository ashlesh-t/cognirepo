# CogniRepo — Phased Implementation Roadmap (planning index)

Generated 2026-07-11 from a full evidence-based audit of HEAD (`146627d`, v2.0.0, branch
`development`). Discovery evidence lives in `JIRA/EPIC-*/COGNIREPO-*-Discovery.md`; executable
tickets in `JIRA/`; the working process for downstream sessions in root `skill.md`; resume state
in root `COMPLETED_TASKS.md` and `JIRA/status.yml`.

## Phases

| Phase | Doc | Epic | Version | One-paragraph summary |
|---|---|---|---|---|
| 0 | [00-audit-and-reliability.md](00-audit-and-reliability.md) | COGNIREPO-100 | **2.0.1** | Hard reliability gate. Fixes the audit's confirmed defects: manifest regression (two tools missing again after [1.1.3] fixed them), episodic ID collision after rotation, the uncommitted requirements.txt diff that reverts CVE fixes, watcher debounce/rename/orphan issues, graph.pkl quarantine, layer-invariant upward imports, and a docs truth pass. Nothing later starts before this is signed off. |
| 1 | [01-kg-episodic-hardening.md](01-kg-episodic-hardening.md) | COGNIREPO-200 | **2.1.0** | The user's two focus areas. Graph: integrity metrics + doctor wiring, similarity edges, Go call-graph completion, dynamic-dispatch annotation. Episodic: unified `get_timeline` (sessions+episodes+decisions+errors) with a human-readable rollup, archive search, embedding cache — designed as the data foundation Phase 2 reads. |
| 2 | [02-insights-feature.md](02-insights-feature.md) | COGNIREPO-300 | **2.2.0** | `cognirepo insights` CLI + `generate_insights` MCP tool producing a single self-contained, light/dark, offline HTML report at `.claude/insights/<repoName>-insights.html` (explicit CLAUDE.md storage-exception amendment), idempotent in-place updates, every fact traceable to a real record, markdown twin indexed by CogniRepo's own `search_docs` (dogfood). |
| 3 | [03-agentic-mood-layer.md](03-agentic-mood-layer.md) | COGNIREPO-400 | **2.3.0** | Backend mood signal (`frustrated`/`neutral`/`flow`) derived from existing behaviour data into `get_user_profile`/`get_agent_bootstrap` (zero new tools), 3 named opt-in personas, headlined by the "caveman" economy persona — output-side token reduction with a dedicated measurement harness and a hard accuracy-non-inferiority gate. |
| 4 | [04-subagent-delegation.md](04-subagent-delegation.md) | COGNIREPO-500 | **2.4.0** | Data enrichment, not orchestration: `context_pack` gains a conditional `delegation_hints` block grouping graph-disconnected hits (independence computed inside `hybrid.py`) plus TODO surfacing, so a consuming Claude session can choose to delegate. Zero manifest growth; key absent when nothing is parallelizable. |
| 5 | [05-oss-growth.md](05-oss-growth.md) | COGNIREPO-600 | **2.4.1** | Make the claims as reliable as the code: benchmark re-run + README/METRICS reconciliation (4-vs-6-vs-3 repo inconsistency, fastapi 0% recall), good-first-issue funnel seeded from audit findings, registry artifacts verified generated, Discord link, insights-report showcase. |

## Dependency order

`0 → 1 → 2`, `1 → 3`, `1 → 4`, `(101) → 5` — Phase 0 gates everything; Phases 3 and 4 need only
Phase 1 (not 2) and are mutually independent; Phase 5 can start any time after COGNIREPO-101,
except its showcase sub-task (needs EPIC-300). Epics are internally sign-off-gated per
`skill.md`.

## Version sequence (internally consistent chain)

2.0.0 (shipped) → **2.0.1** (P0, pure fixes) → **2.1.0** (P1, additive) → **2.2.0** (P2,
additive feature) → **2.3.0** (P3, additive opt-in) → **2.4.0** (P4, additive enrichment) →
**2.4.1** (P5, docs/metadata). Each bumps from its predecessor. `version.yml` is the single
source (synced by `scripts/sync_version.py`).

---

## Final self-check (Output 4 of the audit brief)

**Ground Rule 1 items — re-verified fresh at HEAD, verdicts:**
- (1a) Four v1.1.0 P0 blockers: **all FIXED** — `core/vector_db/local_vector_db.py:75-108,282,315`
  (FAISS mtime reload); `intelligence/indexer/ast_indexer.py:2051-2078` (atomic write +
  self-heal); `ast_indexer.py:84-141` (staging unskipped + `unskip_dirs`);
  `data/graph/knowledge_graph.py:283-354` (bounded subgraph). K8s-scale behavior:
  cannot-determine-without-running at that scale. The "~14 unexecuted tests" were manual-suite
  sections; that suite no longer exists in the repo — **superseded** by the JIRA TEST_SUITEs.
  Automated suite at HEAD: 1203 passed / 5 skipped / 0 failed.
- (1b) IMPROVEMENTS.md: upward import **still true** (`behaviour_tracker.py:540`, plus 4 more
  found); "4 missing manifest tools" **half-stale** — `search_token`/`get_agent_bootstrap` are
  present; `find_symbol_path`/`get_service_endpoints` missing = **regression of the [1.1.3]
  fix** (CHANGELOG.md:62). Exact reconciliation: 34 real decorators (the 35th grep hit is a
  comment at `mcp_server.py:2587`) vs 32 manifest entries.
- (1c) README "Future Plans"/FEATURES §16 spot-checks: CALLS_API-never-auto-detected **stale**
  (`http_call_scanner.py`, `org rewire`, doctor check `main.py:864`); similarity-edges-absent
  **accurate**; Go-call-incomplete **partially stale**; FEATURES §15 lists 17 of 85 test files;
  Future Plans headers still say v0.3.0/v0.4.0.
- (requirements.txt) Working-tree diff **reverts committed CVE fixes** `779b113` (names
  GHSA-537c-gmf6-5ccf) and `6083b15` → recommend revert; final call is the user's (D03).

**Ground Rule 2 compliance:** every story names its compliance in its phase doc. Exactly one
proposed CLAUDE.md amendment: Phase 2's `.claude/insights/` storage exception (02-insights
§Architecture-rule compliance), with a stated fallback (`.cognirepo/insights/`) if rejected. All
graph/FAISS access in new work routes through `hybrid.py` or the data layer; all new tools are
stateless `interface/tools/` entries; no model names outside `classifier.py`.

**Version-bump consistency:** chain above; each phase bumps from the previous phase's version.

**Discovery-before-planning:** all six Discovery.md files were written (Stage C) before any
planning or ticket file (Stages D/E) — see COMPLETED_TASKS.md stage log.

**Deltas between the brief and this plan (plain English):**
- The brief's "~34 MCP tools" verified as exactly 34 live (32 in manifest — the defect).
- The brief pointed at "docs/CONTRIBUTING.md 'Adding a CLI Tool'" — that section doesn't exist;
  tickets cite the real recipes in `docs/DEVELOPER_GUIDE.md` (§36, §162) instead.
- The brief asked whether the requirements.txt downgrade was intentional — evidence says it
  undoes CVE commits, so the plan recommends revert but blocks the action on user confirmation
  (D03) rather than deciding unilaterally.
- The manual-test re-run item was re-scoped: MANUAL_TEST_SUITE.md is gone from the repo, so
  instead of resurrecting it the JIRA TEST_SUITE.md files become the manual suite of record.
- Phase 3's mood signal was scoped to **zero new MCP tools** (extend existing payloads) — the
  brief allowed "likely a new get_agent_mood() tool", but Ground Rule 3 (manifest token cost +
  an extra required call) argued against it; noted in 03's stories.
- Phase 4's scope-as-enrichment was accepted as-is (the brief invited disagreement; none
  registered — an execution layer would break the architecture invariants).
- README's "~4,100 tokens" claim measured at 3,380 for the 32 manifest entries — judged
  approximately honest (34 tools + docstring overhead), not flagged as a defect.
