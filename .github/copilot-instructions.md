# CogniRepo — GitHub Copilot Instructions

CogniRepo MCP tools are available. Use them before any native file exploration.
Most valuable on codebases ≥ 15K LOC.

## Session start (call in this order every session)

1. `mcp_cognirepo_get_session_brief` — architecture, hot symbols, index health
2. `mcp_cognirepo_get_last_context` — resume where last agent left off (cross-agent handoff)
3. `mcp_cognirepo_get_user_profile` — user's interaction style; apply `framing_hints` to ALL responses
4. `mcp_cognirepo_get_error_patterns` — past recurring errors; do not repeat them

## Tool routing

| Task | Use first |
|------|-----------|
| Find where a function lives | `mcp_cognirepo_lookup_symbol` |
| Understand code or a query | `mcp_cognirepo_context_pack` |
| Find all callers of a function | `mcp_cognirepo_who_calls` |
| Past decisions or bugs | `mcp_cognirepo_episodic_search` |
| Architecture overview | `mcp_cognirepo_architecture_overview` |
| Exact string/token search | `mcp_cognirepo_search_token` |
| Semantic code search | `mcp_cognirepo_semantic_search_code` |
| Search documentation | `mcp_cognirepo_search_docs` |
| Symbol neighbourhood graph | `mcp_cognirepo_subgraph` |
| Module dependency tree | `mcp_cognirepo_dependency_graph` |
| Explain a recent change | `mcp_cognirepo_explain_change` |
| Store a memory or discovery | `mcp_cognirepo_store_memory` |
| Retrieve past memories | `mcp_cognirepo_retrieve_memory` |
| Record architectural decision | `mcp_cognirepo_record_decision` |
| Log an event or milestone | `mcp_cognirepo_log_episode` |
| Record an error encountered | `mcp_cognirepo_record_error` |
| Avoid repeating past errors | `mcp_cognirepo_get_error_patterns` |
| User states a preference | `mcp_cognirepo_record_user_preference` |
| List registered org repos | `mcp_cognirepo_list_org_context` |
| Search across all repos | `mcp_cognirepo_org_wide_search` |
| Repo dependency graph | `mcp_cognirepo_org_dependencies` |
| Trace symbol across services | `mcp_cognirepo_cross_repo_traverse` |
| Link two repos | `mcp_cognirepo_link_repos` |

## Behaviour rules

- Apply `framing_hints` from `get_user_profile()` to every response.
- When user's request conflicts with past pattern, ask ONE clarifying question first.
- Call `mcp_cognirepo_record_user_preference` IMMEDIATELY when user says "I prefer...", "always use...", or "never do...".
- Call `mcp_cognirepo_record_decision` for non-trivial architectural choices.
- Call `mcp_cognirepo_record_error` whenever an error is hit.

## Fallback rules

- `context_pack` returns `status: "no_confident_match"` → grep/file read directly
- `context_pack` returns `status: "index_empty"` → run `cognirepo index-repo .` first
- `who_calls` returns `found_via: "dynamic_dispatch_fallback"` → treat as medium confidence

## NEVER

- NEVER read files >100 lines without calling `context_pack` first
- NEVER assume where a symbol lives — call `lookup_symbol` first
- NEVER use grep for semantic queries — use `semantic_search_code`
