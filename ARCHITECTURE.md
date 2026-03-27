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
| `retrieval/` | Hybrid 4-signal scoring | Direct FAISS calls |
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
FAISS      (4-signal merge:       NetworkX
episodic   vector + graph         behaviour
embeddings + AST + episodic)      tracker
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
orchestrator/classifier.py      — score query → FAST / BALANCED / DEEP tier
    │
    ▼
orchestrator/context_builder.py — hydrate ContextBundle from all 5 sources
    │  (semantic memories, graph context, AST hits, episodic events, session history)
    ▼
orchestrator/router.py          — local resolver (FAST) or model API call
    │
    ├── anthropic_adapter.py    — Claude
    ├── gemini_adapter.py       — Gemini
    ├── grok_adapter.py         — Grok / xAI
    └── openai_adapter.py       — OpenAI / Azure / Ollama / LM Studio
    │
    ▼
orchestrator/session.py         — persist exchange to .cognirepo/sessions/
```

---

## Storage Layout

All CogniRepo data lives under `.cognirepo/` in the project root. Nothing is written outside it.

```
.cognirepo/
  config.json                  — project config (model registry, JWT secret, session cap)
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
| Imperative + abstract combo (implement, build, …) | +4 | binary |

**Score thresholds:**
- 0–6   → **FAST** — quick lookup, factual, single-entity
- 7–14  → **BALANCED** — moderate reasoning
- 15+   → **DEEP** — cross-file, architectural, ambiguous

**Hard overrides** (bypass score):
- `"full context"` / `"everything related"` → always DEEP
- Single word / single symbol → always FAST
- Error trace in query → always BALANCED minimum

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
| `retrieval-pipeline.png` | Hybrid 4-signal retrieval detail |
| `multi-agent.png` | gRPC-based multi-agent topology |
