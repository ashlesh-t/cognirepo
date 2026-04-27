# CogniRepo Context for {project_name}

This repo uses CogniRepo for indexed symbol lookup, semantic memory, knowledge graph,
episodic history, and user behaviour profiling.

## Before Suggesting Code Changes

Check if a CogniRepo context pack is available at:
`~/.cognirepo/{project_name}/last_context.json`

This file is refreshed automatically and contains:
- Recent decisions and architectural choices
- Known quirks and dynamic dispatch patterns
- Hot symbols from recent git activity

## Key MCP Tools

| Tool | When |
|------|------|
| `get_session_brief` | Session start — architecture + hot symbols + health |
| `get_last_context` | Session start — resume from last agent |
| `get_user_profile` | Session start — apply framing_hints to all responses |
| `get_error_patterns` | Session start — avoid repeating past errors |
| `context_pack(query)` | Before reading any file >100 lines |
| `lookup_symbol(name)` | Before grepping for a function |
| `who_calls(fn)` | Before grepping for callers |
| `episodic_search(topic)` | Find past decisions or bugs |
| `record_decision(summary, rationale)` | After making an architectural choice |
| `record_user_preference(key, value)` | When user states a preference |
| `record_error(type, message)` | When an error is encountered |
| `store_memory(text)` | After solving bugs or discoveries |

## CLI Commands

- Index: `cognirepo index-repo .`
- Session brief: `cognirepo prime`
- Health check: `cognirepo doctor`
- Full setup: `cognirepo setup`

## Known Patterns

Dynamic dispatch patterns in this repo may not appear in static call graphs.
Use the `who_calls` MCP tool to get both static and string-literal hits.

If `who_calls` returns `found_via: dynamic_dispatch_fallback`, verify with a file read.

If `context_pack` returns `status: "no_confident_match"`, fall back to grep/file read directly.
If `context_pack` returns `status: "index_empty"`, run `cognirepo index-repo .` first.
