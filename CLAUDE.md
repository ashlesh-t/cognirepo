# CLAUDE.md

CogniRepo — local cognitive infrastructure layer for AI agents.
Semantic memory (FAISS) + knowledge graph + AST index + MCP server.
Goal: cut token overhead and context loss between AI sessions, not add complexity.

## Key rules

- All storage lives under `.cognirepo/` in the project root, with one exception: cross-agent handoff snapshots are written to `~/.cognirepo/<repo>/last_context.json` so multiple agent processes (Claude, Gemini, Cursor) can share context across sessions. The org-level dependency graph lives at `~/.cognirepo/org_graph.pkl` for the same reason.
- Model names only in `orchestrator/classifier.py`. No hardcoding elsewhere.
- `retrieval/hybrid.py` owns all retrieval. Never call FAISS or the graph directly from tools.
- Tools in `tools/` are the single entry point. Stateless, no cross-tool calls.

## Session start sequence (run in this order)

1. `get_session_brief()` — architecture + hot symbols + index health
2. `get_last_context()` — what the last agent was looking at

## Tool routing (for Claude Code agents using this repo)

| Task | Use this first |
|------|---------------|
| Session start | `get_session_brief()` then `get_last_context()` |
| Find where a function lives | `lookup_symbol("fn_name")` |
| Understand a module or query | `context_pack("question")` |
| Find callers of a function | `who_calls("fn_name")` |
| Past decisions / bugs | `episodic_search("topic")` |
| Architecture overview | `architecture_overview()` |
| Resume previous session | `get_last_context()` |

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
