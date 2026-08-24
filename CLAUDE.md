# CLAUDE.md

CogniRepo — local cognitive infrastructure layer for AI agents.
Semantic memory (FAISS) + knowledge graph + AST index + MCP server.
Goal: cut token overhead and context loss between AI sessions, not add complexity.

## Key rules

- All storage lives under `.cognirepo/` in the project root, with these exceptions: cross-agent handoff snapshots are written to `~/.cognirepo/<repo>/last_context.json` so multiple agent processes (Claude, Gemini, Cursor) can share context across sessions; the org-level dependency graph lives at `~/.cognirepo/org_graph.pkl` for the same reason; and generated human-facing reports (currently `cognirepo insights`) are written to `.claude/insights/<repoName>-insights.html` in the project root — these are presentation artifacts for the human + their agent tooling, not machine state, so keeping them out of `.cognirepo/` avoids polluting index/memory storage, and `.claude/` is already the agent-facing, gitignored surface. The machine-readable twin remains under `.cognirepo/docs/`.
- Org graph model: main repo = hub/parent. Sub-repos/microservices are registered as children via `cognirepo init --parent-repo <path>`. Edges are IMPORTS/CALLS_API/SHARES_SCHEMA/CHILD_OF/DISCOVERED. AI agents add DISCOVERED edges dynamically via `link_repos()`. Children can be interconnected.
- Model names only in `intelligence/orchestrator/classifier.py`. No hardcoding elsewhere.
- `intelligence/retrieval/hybrid.py` owns all retrieval. Never call FAISS or the graph directly from tools.
- Tools in `interface/tools/` are the single entry point. Stateless, no cross-tool calls.
- When ever any code parts get updated and if the document existing ones dont cover or needs changes ,then update the docs accordingly.
 
## Session start sequence (run in this order)

1. `get_session_brief()` — architecture + hot symbols + index health
2. `get_last_context()` — what the last agent was looking at
3. `get_user_profile()` — user's interaction style; apply `framing_hints` to ALL responses
4. `get_error_patterns()` — past recurring errors; avoid repeating them

## Behavioral confirmation rule

After `get_user_profile()`, apply `framing_hints` to every response (depth, vocabulary, code-focus).
`get_user_profile()`/`get_agent_bootstrap()` also carry a `mood` signal ({state, evidence,
suggested_adaptation}) derived from recent errors/queries/edits — neutral with empty evidence on
sparse data. **Precedence: explicit user request > persona > framing_hints/mood.** A `mood` of
"frustrated" means act on `suggested_adaptation` (e.g. verify against `get_error_patterns` before
proposing fixes), not adopt a tone — it never overrides what the user actually asked for.
**When ambiguity detected:** if the user's current request conflicts with their established pattern
(e.g. they always ask for concise answers but this request seems to want a long walkthrough),
ask ONE short clarifying question before proceeding. Do not assume — confirm.
**After every session:** call `record_decision()` for architectural choices, `log_episode()` for
milestones, `record_error()` for any errors hit. This updates the profile for next session.

## Personas (COGNIREPO-402, COGNIREPO-403)

Opt-in only — **never enable a persona unless the user explicitly asks.** Set via
`record_user_preference("persona", "<name>")`; read from `get_user_profile()['active_persona']` /
`['persona_behavior']` — absent entirely when unset (no behavior change from pre-402 baseline).
Exactly three, each a concrete behavior delta, never a decorative label:
- **mentor** — retrieval depth +1 (include episodic context by default), full explanations, link
  responses to related past decisions/history.
- **pair** — the default-equivalent: current behavior plus mood-aware phrasing only.
- **caveman** — economy/telegraphic output (status: **experimental** — 57.3% median reduction
  measured, but missed the strict accuracy-delta gate; see `docs/METRICS.md`). When active,
  `get_user_profile()['output_contract']`
  carries the exact instruction: **compress style, never content** — headline verdict first,
  minimal factual lines, but every file:line reference, number, and caveat must survive; only
  preamble/hedging/restatement/transitions get dropped. Never trade accuracy for brevity (see
  `docs/USAGE.md#personas` for before/after examples). The profile may also carry a one-line,
  dismissible `persona_suggestion` after sustained QUICK-tier usage — advisory only, it never
  self-enables.

## Tool routing (for Claude Code agents using this repo)

| Task | Use this first |
|------|---------------|
| Session start | `get_session_brief()` → `get_last_context()` → `get_user_profile()` → `get_error_patterns()` |
| Find where a function lives | `lookup_symbol("fn_name")` |
| Understand a module or query | `context_pack("question")` |
| Find callers of a function | `who_calls("fn_name")` |
| Past decisions / bugs | `episodic_search("topic")` |
| Architecture overview | `architecture_overview()` |
| Resume previous session | `get_last_context()` |
| Record architectural decision | `record_decision("summary", "rationale")` |
| Log an event or milestone | `log_episode("event text")` |
| Link two repos discovered to be related | `link_repos(src, dst, "discovered")` |
| User corrects your interpretation | `record_user_preference("query_rewrite", "wrong phrasing", context="what they actually meant")` |
| Store user's style/format preference | `record_user_preference("key", "value")` |
| User's interaction style | `get_user_profile()` — then apply framing_hints |
| Avoid repeating past errors | `get_error_patterns()` — check before proposing a fix |
| "What happened recently" (sessions + episodes + decisions + errors, one merged view) | `get_agent_bootstrap()`'s `recent_timeline` field (last 5, past 7 days) — replaces the `get_session_history` + `episodic_search` + `get_error_patterns` 3-call stitch. For a custom window/rollup, call `data.memory.timeline.merge()`/`rollup()` directly |
| Record an error that occurred | `record_error("ErrorType", "message")` |
| Repo history report ("what happened in this repo") | `generate_insights(since="90d")` — returns a path, not content; surface the link |

## Org search routing (pick the right tool)

| Goal | Tool |
|------|------|
| Search one repo's index | `context_pack(query)` — always first |
| Search all registered repos | `org_wide_search(query)` |
| List registered repos + edges | `org_dependencies()` |
| Traverse from one repo to its deps/dependents | `cross_repo_traverse(symbol, start_repo)` |
| Text search across org (fallback) | `org_search(query)` — fallback when index is sparse |
| Link two repos | `link_repos(src, dst, edge_kind)` |

**Rule:** `org_wide_search` > `org_search`. Use `org_search` only when `org_wide_search` returns nothing.

## Microservice org graph

Register microservices as child repos:
```bash
cognirepo init --parent-repo /path/to/monorepo --service-type rest_api --port 8080 --api-base-url /api/v1
```
Then `link_repos(src, dst, "CALLS_API")` to wire API call relationships.
`cross_repo_traverse()` walks the full service graph. `org_dependencies()` shows the tree.

**NEVER** use `Read` or `grep` to explore code before calling `context_pack` first.
**NEVER** assume where a function lives — call `lookup_symbol` first.

**Fallback:** if `context_pack` returns `status: "no_confident_match"` or `status: "index_empty"`
→ grep/Read directly is appropriate.

**Bootstrap:** call `get_session_brief()` via MCP at the start of a session (or run
`cognirepo prime` in the terminal) to get architecture summary, hot symbols, and recent
decisions. Then call `get_last_context()` to resume where the last agent left off.

## Commands

```bash
cognirepo setup                 # one-command onboarding (init + index + MCP config)
cognirepo init                  # scaffold .cognirepo/ and config
cognirepo index-repo [path]     # AST-index a codebase
cognirepo store-memory <text>   # save a semantic memory
cognirepo retrieve-memory <q>   # similarity search
cognirepo search-docs <q>       # search indexed docs
cognirepo doctor                # health check
cognirepo benchmark             # measure token reduction
cognirepo prime                 # bootstrap session context (CLI version of get_session_brief)
cognirepo org rewire            # repair cross-service CALLS_API edges (run after indexing all services)
```

## Stack

Python 3.11+ · FAISS · fastembed/ONNX (all-MiniLM-L6-v2, dim 384) · NetworkX ·
tree-sitter · FastMCP · argparse (CLI) · tiktoken

## Microservice detection

`interface/cli/service_detect.py::_SERVICE_MARKERS` maps project marker filenames → service type.
This list **MUST stay in sync** with `intelligence/indexer/language_registry.py::_GRAMMAR_MAP`.
Whenever a new language is added to `language_registry`, add its build file marker here too.

## Dev detail

See `.claude/CLAUDE.md` (gitignored) — repo layout, algorithm flows, checklists.
See `.claude/skills.md` (gitignored) — reusable patterns for adding tools, languages, tests.
