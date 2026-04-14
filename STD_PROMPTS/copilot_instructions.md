# CogniRepo Context for {project_name}

This repo uses CogniRepo for indexed symbol lookup, semantic memory, and context retrieval.

## Before Suggesting Code Changes

Check if a CogniRepo context pack is available at:
`~/.cognirepo/{project_name}/last_context.json`

This file is refreshed automatically and contains:
- Recent decisions and architectural choices
- Known quirks and dynamic dispatch patterns
- Hot symbols from recent git activity

## Key Architectural Decisions

Query CogniRepo for decisions via:
```
cognirepo retrieve-learnings "architecture"
cognirepo retrieve-learnings "decisions"
```

## Known Patterns

Dynamic dispatch patterns in this repo may not appear in static call graphs.
Use `cognirepo who-calls <fn>` to get both static and string-literal hits.

If `who_calls` returns `found_via: dynamic_dispatch_fallback`, verify with a file read.

## Keeping Context Fresh

- Index: `cognirepo index-repo .`
- Seed from git: `cognirepo seed --from-git`
- Session brief: `cognirepo prime`
- Health check: `cognirepo doctor`
