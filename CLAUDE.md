# CLAUDE.md

CogniRepo — local cognitive infrastructure layer for AI agents.
Semantic memory (FAISS) + knowledge graph + AST index + MCP server.
Goal: cut token overhead and context loss between AI sessions, not add complexity.

## Key rules

- All storage lives under `.cognirepo/` in the project root, with one exception: cross-agent handoff snapshots are written to `~/.cognirepo/<repo>/last_context.json` so multiple agent processes (Claude, Gemini, Cursor) can share context across sessions. The org-level dependency graph lives at `~/.cognirepo/org_graph.pkl` for the same reason.
- Org graph model: main repo = hub/parent. Sub-repos/microservices are registered as children via `cognirepo init --parent-repo <path>`. Edges are IMPORTS/CALLS_API/SHARES_SCHEMA/CHILD_OF/DISCOVERED. AI agents add DISCOVERED edges dynamically via `link_repos()`. Children can be interconnected.
- Model names only in `orchestrator/classifier.py`. No hardcoding elsewhere.
- `retrieval/hybrid.py` owns all retrieval. Never call FAISS or the graph directly from tools.
- Tools in `tools/` are the single entry point. Stateless, no cross-tool calls.

## Session start sequence (run in this order)

1. `get_session_brief()` — architecture + hot symbols + index health
2. `get_last_context()` — what the last agent was looking at
3. `get_user_profile()` — user's interaction style; apply `framing_hints` to ALL responses
4. `get_error_patterns()` — past recurring errors; avoid repeating them

## Behavioral confirmation rule

After `get_user_profile()`, apply `framing_hints` to every response (depth, vocabulary, code-focus).
**When ambiguity detected:** if the user's current request conflicts with their established pattern
(e.g. they always ask for concise answers but this request seems to want a long walkthrough),
ask ONE short clarifying question before proceeding. Do not assume — confirm.
**After every session:** call `record_decision()` for architectural choices, `log_episode()` for
milestones, `record_error()` for any errors hit. This updates the profile for next session.

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
| Record an error that occurred | `record_error("ErrorType", "message")` |

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
```

## Stack

Python 3.11+ · FAISS · sentence-transformers (all-MiniLM-L6-v2, dim 384) · NetworkX ·
tree-sitter · FastMCP · Typer · tiktoken

## Dev detail

See `.claude/CLAUDE.md` (gitignored) — repo layout, algorithm flows, checklists.
See `.claude/skills.md` (gitignored) — reusable patterns for adding tools, languages, tests.
