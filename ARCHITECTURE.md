# CogniRepo — Architecture

This document is the authoritative reference for CogniRepo's system design, component
responsibilities, and data flow. Read this before touching any code.

---

## The Single Rule

> **`tools/` is the only entry point to the memory engine.**
>
> MCP, REST, and gRPC are thin protocol wrappers. No business logic lives in adapters.
> If you are writing logic in `server/mcp_server.py`, `api/routes/`, or `rpc/server.py`
> — stop. Move it to a function in `tools/` and call that function from the adapter.

PRs that put logic directly in adapters will not be merged. This rule is what keeps
all three transports consistent and testable.

---

## Component Responsibility Table

| Package | Owns | Does not own |
|---|---|---|
| `memory/` | FAISS store/retrieve, episodic log, embeddings, circuit breaker | Retrieval scoring |
| `graph/` | NetworkX graph structure, behaviour tracker | Embedding, retrieval |
| `indexer/` | tree-sitter parsing, file watching, reverse index | Graph building |
| `retrieval/` | Hybrid 3-signal scoring (vector + graph + behaviour); AST is a pre-scorer | Direct FAISS calls |
| `tools/` | Architecture rule enforcement — all callers go through here | Business logic |
| `orchestrator/` | Classify, build context, route to model, post-process | Storage |
| `server/` | MCP stdio adapter only | Any logic |
| `api/` | REST adapter + JWT auth only | Any logic |
| `rpc/` | gRPC adapter + context store only | Any logic |
| `security/` | Encryption at rest, keychain integration | Auth (that is `api/`) |
| `adapters/` | OpenAI spec + Cursor config export | Any logic |

---

## Data Flow

```
User / AI Tool
    │
    ├── MCP stdio         server/mcp_server.py
    ├── REST (JWT)        api/main.py
    └── gRPC              rpc/server.py
              │
         tools/           ← ONLY entry point to memory engine
              │
    ┌─────────┼──────────────────────┐
    ▼         ▼                      ▼
memory/    retrieval/hybrid.py    graph/
FAISS      (3-signal merge:       NetworkX
episodic   vector + graph         behaviour
embeddings + behaviour)           tracker
              │
         ↑ AST pre-scorer (expands candidates)
         ↑ Episodic side-channel (separate BM25 pipeline)
              │
         indexer/
         tree-sitter parser
         (Python, JS, TS, Java, Go, Rust, C++)
              │
         .cognirepo/
         (Fernet encrypted if storage.encrypt: true)
```

### Orchestrator path (CLI `ask` / REPL)

```
cognirepo ask "why is auth slow?"
    │
    ▼
orchestrator/classifier.py      — score query → QUICK / STANDARD / COMPLEX / EXPERT tier
    │                              errors → .cognirepo/errors/<date>.log (no raw tracebacks)
    ▼
orchestrator/context_builder.py — hydrate ContextBundle from all 5 sources
    │  (semantic memories, graph context, AST hits, episodic events, session history)
    ▼
orchestrator/router.py          — local resolver (QUICK) or model API call
    │                              on error: user-friendly message + log to errors/
    ├── local_adapter.py        — zero-API local resolver (QUICK tier primary)
    ├── grok_adapter.py         — Grok / xAI  (STANDARD tier primary)
    ├── gemini_adapter.py       — Gemini       (STANDARD/COMPLEX primary)
    ├── anthropic_adapter.py    — Claude       (EXPERT primary)
    └── openai_adapter.py       — OpenAI / Azure / Ollama / LM Studio (fallback)
    │
    ▼
orchestrator/session.py         — persist exchange to .cognirepo/sessions/
```

### Init wizard + MCP connector setup

```
cognirepo init   (interactive TTY)
    │
    ▼
cli/wizard.py           — 7-step powerlevel10k-style prompt
    │  project name, multi-model, Redis, encrypt, languages, MCP targets, API port
    ▼
cli/init_project.py     — scaffold dirs, write config.json
    │
    ├── .cognirepo/config.json   — project_name, models{QUICK/STANDARD/COMPLEX/EXPERT},
    │                              multi_agent, redis, storage.encrypt
    ├── .claude/CLAUDE.md        — project instructions (from STD_PROMPTS/claude_mcp.md)
    ├── .claude/settings.json    — MCP connector: cognirepo-<name> → cognirepo serve --project-dir
    ├── .gemini/COGNIREPO.md     — Gemini instructions (from STD_PROMPTS/gemini_mcp.md)
    └── .gemini/settings.json    — MCP connector: cognirepo-<name> → cognirepo serve --project-dir
```

### Project isolation (multi-project / multi-team)

```
Team A opens /projects/alpha/   Team B opens /projects/beta/
    │                               │
    ├── .claude/settings.json       ├── .claude/settings.json
    │   cognirepo-alpha             │   cognirepo-beta
    │   --project-dir /projects/alpha  --project-dir /projects/beta
    │                               │
    ▼                               ▼
cognirepo serve                 cognirepo serve
  --project-dir /projects/alpha   --project-dir /projects/beta
    │                               │
    ▼                               ▼
/projects/alpha/.cognirepo/     /projects/beta/.cognirepo/
  vector_db/ graph/ index/        vector_db/ graph/ index/
  (alpha's memories only)         (beta's memories only)
```

Each AI tool connection (Claude, Gemini, etc.) is a separate OS process locked to one
project directory via `--project-dir`. Data **never crosses project boundaries**.

---

## Storage Layout

All CogniRepo data lives under `.cognirepo/` in the project root. Nothing is written outside it.

```
.cognirepo/
  config.json                  — project config (project_name, model registry, multi_agent, redis)
  vector_db/
    faiss.index                — FAISS flat index (sentence-transformer embeddings)
    metadata.json              — per-vector metadata (text, source, importance, timestamp)
  graph/
    graph.pkl                  — serialised NetworkX DiGraph
  index/
    ast_index.json             — AST reverse index: symbol → [(file, line), ...]
  episodic/
    episodic.json              — append-only event journal (JSON lines)
  sessions/
    <uuid>.json                — individual conversation session files
    current.json               — pointer to the most recent session
  errors/
    <date>.log                 — timestamped error log (no raw tracebacks to users)

.claude/                       — Claude Code project-level config (auto-generated by init)
  CLAUDE.md                    — instructions for Claude on how to use CogniRepo tools
  settings.json                — MCP connector (cognirepo-<name> --project-dir <path>)

.gemini/                       — Gemini CLI project-level config (auto-generated by init)
  COGNIREPO.md                 — instructions for Gemini on how to use CogniRepo tools
  settings.json                — MCP connector (cognirepo-<name> --project-dir <path>)

STD_PROMPTS/                   — bundled markdown templates (inside the cognirepo package)
  claude_mcp.md                — template rendered → .claude/CLAUDE.md
  gemini_mcp.md                — template rendered → .gemini/COGNIREPO.md
```

---

## Complexity Classifier Signals

`orchestrator/classifier.py` — rule-based multi-signal weighted scorer. No ML, no training data.

| Signal | Weight | Logic |
|--------|--------|-------|
| Reasoning keywords (why, compare, refactor, …) | +3 | per keyword |
| Lookup keywords (what is, show, list, find, get) | -2 | per keyword |
| Vague referents (it, this, that without clear noun) | +2 | per unresolved ref |
| Cross-entity count (fn/file/class mentions) | +1.5 | per entity above 2 |
| Context dependency (episodic/graph history ref) | +3 | binary |
| Query token length | +0.5 | per 10 tokens after first 20 |
| Imperative + abstract combo (implement, build, …) | +5 | binary |

<!-- Thresholds are authoritative here. See _TIER_* constants in orchestrator/classifier.py -->
**Score thresholds:**
- ≤2    → **QUICK** — single-token, trivial — local resolver (zero-API)
- ≤4    → **STANDARD** — quick lookup, factual, single-entity — Gemini Flash / Grok
- ≤9    → **COMPLEX** — moderate reasoning — Gemini Flash / Claude Sonnet
- >9    → **EXPERT** — cross-file, architectural, ambiguous — Claude Opus

**Hard overrides** (bypass score):
- `"full context"` / `"everything related"` → always EXPERT
- Single word / single symbol → always **QUICK**
- Error trace in query → always COMPLEX minimum

**Error handling:** All model errors write to `.cognirepo/errors/<date>.log`. Users see a
friendly one-liner message, never a raw Python traceback.

---

## Multi-Language Indexing

tree-sitter replaces the stdlib `ast` module as the primary parser. It provides a consistent
CST-based API across 40+ languages via grammar packages, without any Python-specific quirks.

Python indexing continues to work even without `tree-sitter-python` installed, via a stdlib
`ast` fallback path. All other languages require the corresponding grammar package.

Install additional languages:

```bash
pip install cognirepo[languages]   # Python, JS, TS, Java, Go, Rust, C++
```

The `indexer/language_registry.py` module handles lazy grammar loading and caching.
`is_supported(path)` returns `True` if the grammar is installed or the file is `.py`.

Full language support details and the roadmap for adding new languages: [LANGUAGES.md](LANGUAGES.md)

---

## Adding a Model Adapter

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide. In brief:

1. Create `orchestrator/model_adapters/<name>_adapter.py`
2. Implement `call(prompt, system, tools, max_tokens) → ModelResponse` and
   `stream_call(prompt, system, tools) → Iterator[str]`
3. Add the provider to the fallback chain in `orchestrator/router.py` and document
   it in the provider table in `USAGE.md`

---

## Adding a CLI Tool

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide. In brief:

1. Create `tools/<name>.py` — wraps existing `memory/` or `graph/` methods, no direct FAISS calls
2. Add `@mcp.tool()` decorated function in `server/mcp_server.py`
3. Add REST route in `api/routes/` — run `cognirepo export-spec` to regenerate
   `server/manifest.json`

---

## Diagrams

Rendered architecture diagrams are in `docs/architecture/diagrams/`. These are placeholders
for v0.1.0 — they will be replaced with proper diagrams before v0.2.0.

| File | Description |
|------|-------------|
| `system-overview.png` | Full component map |
| `data-flow.png` | Request path from tool call to model response |
| `retrieval-pipeline.png` | Hybrid 3-signal retrieval pipeline (AST pre-scorer → vector+graph+behaviour merge) |
| `multi-agent.png` | gRPC-based multi-agent topology |
