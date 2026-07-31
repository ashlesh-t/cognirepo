You are doing a deep, evidence-based audit and implementation-roadmap design for CogniRepo, a local
cognitive-infrastructure MCP server for AI coding agents (FAISS semantic memory + NetworkX knowledge
graph + AST reverse index + episodic event log, offline-first, 34-ish MCP tools). Repo root:
/home/ashlesh/my_works/cognirepo. Read CLAUDE.md and .claude/CLAUDE.md first — they are binding
architecture rules, not suggestions.

YOUR JOB IS ANALYSIS AND PLANNING ONLY. Do not write implementation code. Your output is documentation
and a Jira mirror, structured so a separate Claude Code coding session can pick up any one epic file
and implement it without needing this conversation's context.


## GROUND RULES — READ FIRST


1. TRUST NOTHING SECOND-HAND. This repo's own docs, CHANGELOG, IMPROVEMENTS.md, and its auto-memory
   files (~/.claude/projects/-home-ashlesh-my-works-cognirepo/memory/) describe a state that may be
   stale — the codebase just went through a breaking v2.0.0 restructure (see git log: 146627d,
   6b0c83d, 45b0b41, and the [2.0.0] entry in CHANGELOG.md). Specifically re-verify against current
   HEAD, don't just cite the doc:
     a. MEMORY.md's project_v110_release_qa.md records a 2026-06-11 NO-GO verdict with 4 P0 blockers
        (stale FAISS reload, AST index corruption, context_pack empty on k8s, subgraph memory
        blowup) and ~14 unexecuted tests. Determine current status of each: fixed / still-open /
        regressed / cannot-determine-without-running. Cite file:line evidence either way.
     b. IMPROVEMENTS.md claims 4 MCP tools are missing from _build_manifest() in
        interface/server/mcp_server.py, and that data/graph/behaviour_tracker.py has an upw
        import into interface.tools.store_memory. Verify both are still true post-restructu
        may be a REGRESSION — CHANGELOG.md [1.1.3] already fixed 2 of those exact 4 tools o
        before, then the 2.0.0 manifest rewrite may have dropped the fix again). Get the ex
        tool list via grep -c "@mcp.tool()" interface/server/mcp_server.py vs
        interface/server/manifest.json and reconcile precisely.
     c. Do not assume README.md's "Future Plans" / FEATURES.md §16 "not implemented" sectio
        still accurate — spot-check a sample of each against actual code.

2. RESPECT EXISTING ARCHITECTURE INVARIANTS in every proposal (from docs/ARCHITECTURE.md, r
   CLAUDE.md): interface/tools/ is the sole entry point (stateless, no cross-tool calls);
   intelligence/retrieval/hybrid.py owns all retrieval, nothing calls FAISS or the graph directly;
   model names only live in intelligence/orchestrator/classifier.py; all persistent storage lives
   under .cognirepo/ except two documented exceptions (~/.cognirepo/<repo>/last_context.json,
   ~/.cognirepo/org_graph.pkl). Any new feature that needs a third exception (see the insig
   feature below, which the user wants under .claude/) must be proposed as an explicit CLAUDE.md
   rule amendment with a stated rationale — not a silent violation. Flag if any of your own proposals
   would require breaking one of these rules, and say so explicitly rather than quietly working
   around it.

3. NEVER LOSE THE CORE MISSION: every phase must be justified against "does this reduce Claude's
   token/effort cost, or does it add overhead?" A feature that sounds good but adds latency, adds
   required tool calls, or grows the MCP tool-schema footprint (currently ~4,100 tokens for the tool
   list per README) without a clear reduction elsewhere should be flagged as a risk, not silently
   included.

4. THIS REPO IS THE PRODUCT. Wherever practical, have the plan dogfood CogniRepo's own capabilities
   (e.g. the insights feature and the planning docs themselves should be indexable/retrievable
   through CogniRepo's own tools).

═══════════════════════════════════════════════════════════════════
SCOPE — WHAT TO AUDIT AND PLAN
═══════════════════════════════════════════════════════════════════

Produce a PHASED plan. Phase 0 is a hard reliability gate — nothing in later phases should be
scheduled to start before Phase 0's blockers are closed. Propose a real SemVer version number for
each phase's release (current shipped version is 2.0.0 — do not reuse it; reason about patch vs
minor vs major per phase based on whether it's a pure fix, additive/backward-compatible feature, or
breaking change).

### Phase 0 — Verification & Reliability Audit (gate)
- Re-verify all 4 items under Ground Rule 1 above with file:line evidence.
- Full pass over interface/tools/*.py, interface/server/mcp_server.py, and every MCP tool listed in
  docs/MCP_TOOLS.md: does the implementation match the documented signature/behavior? Any d
  unregistered tools, or manifest drift?
- Indexing reliability specifically (the user's most-repeated pain point — "indexing will not proper
  and stale etc etc"): audit intelligence/indexer/ast_indexer.py, intelligence/indexer/file_watcher.py
  staleness detection, the debounce bug flagged in README's Near-term roadmap ("large repos see
  spurious full re-indexes"), and cognirepo verify-index / doctor's index-health checks. Also audit
  the AST reverse index specifically (symbol→file:line correctness under renames/deletes/moves) —
  this is the "reverse indexing" the user wants hardened, not a new feature.
- Knowledge-graph audit: data/graph/knowledge_graph.py node/edge integrity, orphaned nodes after file
  deletion, graph.pkl corruption/recovery story, subgraph memory blowup claim from Ground R
- Full dependency/security posture check — note the current uncommitted requirements.txt diff
  downgrades cryptography/PyJWT/starlette/urllib3/python-multipart from patched versions; confirm
  whether this is intentional or should be reverted, and check CI security gates (Bandit, T
  Trivy, Snyk per README) still pass against HEAD.
- Test coverage audit against FEATURES.md §15's test inventory — are the ~14 "unexecuted tests" from
  the 2026-06-11 QA verdict now executed? Run what you can; report what you can't run and why.
- Output: docs/planning/00-audit-and-reliability.md

### Phase 1 — Knowledge Graph & Episodic Memory Hardening
The user's two explicitly-named focus areas. Build on, don't replace, existing systems
(data/graph/knowledge_graph.py, data/memory/episodic_memory.py, data/graph/behaviour_tracke
- KG: incorporate README's already-roadmapped items where still relevant — similarity edges,
  Go call-graph completion, dynamic-dispatch/plugin-registry detection (Ansible/Celery patterns
  noted in README) — re-prioritize based on Phase 0 findings, don't re-invent.
- Episodic memory: the user wants it to become the backbone that "keeps track of everything
  very easy for any user to know what's happening." Audit whether get_session_history,
  episodic_search, record_decision, and log_episode together actually deliver a coherent, complete
  timeline today, or whether there are gaps (e.g. decisions not consistently logged, no
  human-readable rollup). This phase's output should also be the data foundation Phase 2's insights
  feature reads from — design them together.
- Output: docs/planning/01-kg-episodic-hardening.md

### Phase 2 — New feature: `<repoName>-insights`
- An HTML report generator summarizing repo history: what was done, how, challenges, branch
  sourced from real data (episodic log + git history + knowledge graph), never fabricated c
- Storage: user wants it under .claude/ — reconcile with Ground Rule 2 (propose the CLAUDE.
  exception explicitly). Decide exact path/filename convention.
- MUST be idempotent: on re-run, detect an existing report for the repo and update it in pl
  rather than duplicating.
- MUST be indexed by CogniRepo itself — decide how (new MCP tool exposing it to search_docs
  context_pack, or ingestion into FAISS/graph at generation time).
- UI bar: "exceptionally good" — single self-contained HTML/CSS/JS (no external requests, w
  offline like everything else in this project), light/dark aware. Claude surfaces a link t
  after generation, not the raw content.
- Design as a new CLI command (cognirepo insights) AND an MCP tool, following the existing
  docs/CONTRIBUTING.md's "Adding a CLI Tool" section (tools/<name>.py → mcp_server.py → exp
- Output: docs/planning/02-insights-feature.md

### Phase 3 — Agentic mood / persona layer
Per user decision: primarily a backend tone signal extending get_user_profile/framing_hints
light persona layer on top — not a heavy new subsystem.
- Derive a session "mood" signal (confidence/frustration/momentum) from existing behaviour_
  signals (error rate from get_error_patterns, retry patterns, query velocity) — likely a n
  get_agent_mood() MCP tool or an extension of get_user_profile()'s existing framing_hints
  Keep this genuinely useful, not decorative — judge every proposed signal against "would t
  actually change what Claude does, or just what it says?"
- A SMALL set of named personas (not an open-ended system) — decide how many, and how they
  concrete behavior changes (retrieval depth, response verbosity, tone).
- THE ONE NOVEL IDEA: a "caveman" economy persona — an ultra-terse, telegraphic output mode
  reduces OUTPUT-side token cost, as the mirror to context_pack's existing INPUT-side reduc
  is the feature most worth getting right — it's a direct, measurable extension of the proj
  value prop (README's headline metric is token reduction). Specify: what triggers it (QUIC
  classifier score? explicit opt-in flag? user profile inference?), what it looks like conc
  (example before/after response pairs), how it's measured (token count comparison, same be
  methodology as docs/METRICS.md), and how it avoids degrading answer quality/accuracy — th
  own "Honest limits" section in README is explicit that it never trades accuracy for compr
  persona must hold that same bar.
- Gate this behind explicit opt-in — do not silently change default Claude behavior for exi
- Output: docs/planning/03-agentic-mood-layer.md

### Phase 4 — Sub-agent grooming / parallel-work delegation
- Scope carefully: CogniRepo is a memory/retrieval layer, not an orchestrator (see Ground R
  interface/tools/ must stay stateless with no cross-tool calls). This phase should NOT mak
  CogniRepo spawn agents itself. Instead scope it as: can CogniRepo's existing context surf
  (context_pack output, graph traversal) be enriched to flag independent/parallelizable wor
  it notices (e.g. unrelated TODOs, files touched that don't share a dependency edge in the
  that a Claude Code session consuming that context can decide to delegate to a subagent? T
  data-enrichment problem, not an execution problem — say explicitly if you disagree and th
  different scope is more honest to the codebase's actual role.
- Output: docs/planning/04-subagent-delegation.md

### Phase 5 — OSS growth / production polish
- Lower-code, GTM-adjacent: README/benchmark polish (more repos beyond the current 6), Disc
  growth actions, contribution-funnel improvements (good-first-issue labeling in CONTRIBUTI
  MCP registry presence (mcp-name, Glama — already partially done per git log, verify curre
  and — notably — the Phase 2 insights-HTML output itself is a natural README showcase asse
  ("here's what CogniRepo generates about your repo") worth cross-referencing.
- Output: docs/planning/05-oss-growth.md

═══════════════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════════════

1. docs/planning/README.md — index of all phases, one-paragraph summary each, dependency or
   proposed version numbers.

2. One file per phase (docs/planning/0N-<slug>.md) using this fixed template for EVERY epic
   every story inside it, so a Claude Code agent can execute directly from the file:
   - **Context / Why** — the problem, cited evidence (file:line, doc quote, or "verified fi
     as of <commit>")
   - **Scope** — explicit in/out of scope
   - **Acceptance criteria** — testable, specific
   - **Stories** — broken into implementable units; each with: files likely touched, depend
     other stories/phases, a suggested test/verification approach (unit test, cognirepo doc
     manual MCP tool call, benchmark run)
   - **Architecture-rule compliance** — explicit confirmation it respects Ground Rule 2, or
     explicit proposed CLAUDE.md amendment if not
   - **Version bump** — proposed SemVer and one-line justification
   - **Risks / open questions** — anything you couldn't verify or that needs a human decisi

3. Jira mirror: create a folder called JIRA, inside it for each phase or milestones create an folder EPIC-< Milestone_Name>-ID: That folder will have COGNIREPO-id.md (an MD file for epic having edic description and Acceptance criteria and Notes well defined).U do all the discovery required for each epic and under each epic folder along with COGNIREPO-id.md create COGNIREPO-< same ID>-Discovery.md\
Then ender that epic we will have story (only for dev tasks) with a flder STORY and inside it COGNIREPO-id.md files which will have detailed Description , and AC Risks or Notes 
and TASKS for small things Testing : This will have evrything required to test currentlyu if u check @~/my_works/cognirepo_test_repo we will have soem good repos on which we can test cognirepo . so check thise things and test what ever things u can and for mannual tests like we need to test the way user uses the product , give test suites for them. for test suites, inside each epic we will have COGNIREPO-< ID>-TEST_SUITE.md which will have which repo to use pre req styeps , promopt , Expected results and Obtained results section . Obtained result section is empty and i will copy it directly. from my observation.
Devide into epics such thaty epics are not dependednt meaning on implementation we can test completely and signoff before strting an epic.
and each epic will have an yml file called status.yml thst will track all necessary state of this .
Commit and PR has to be made for each dev stories .
Any thing we found not working will go into Defects and will follow similar pattern for defects also once we create we need to have the manual test suites and for this we will make commit and PR only once we finish the testing jobs.


4. A final self-check section confirming: every Ground Rule 1 item was re-verified with evi
   (not copied from stale docs); every phase's proposals were checked against Ground Rule 2
   version-bump sequence is internally consistent (each phase bumps from the previous phase
   proposed version, not all from 2.0.0); and a plain-English summary of what changed betwe
   the user asked for and what you're actually recommending (call out anything you dropped,
   or re-scoped, and why).

5. An simpel claude skill.md file to eliminate the directions needed to be given to claude later on implementationlike skill will have detaiiled informations on our JIRA folder structure, execution workflows testing etc , for each story , or any ticket that needs code changes we push it to branch called story/< or defect>/COGNIREPo -< ID> and make an pr to development branch.
6. So your final goal is to analyze repo check for production leevel structures, make all the necessary discoveries Now itself and Update in discovery .md files as given above and also make sure the jira story or anything will have all the information required completely to takew up by claude with expalined description having background stories etyc 