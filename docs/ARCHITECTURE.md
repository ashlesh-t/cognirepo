# CogniRepo Architecture

---

## System Overview

```
User / AI Tool
    │
    ├── MCP stdio              (Claude Desktop, Gemini CLI, Cursor)
    ├── REST API (JWT/FastAPI) (any language, any tool)
    └── gRPC streaming         (multi-agent / inter-model)
              │
         tools/                ← SINGLE ENTRY POINT — all logic here
              │
    ┌─────────┼─────────────────────────┐
    ▼         ▼                         ▼
memory/    retrieval/hybrid.py       graph/
FAISS      4-signal merge:           NetworkX
episodic   vector + graph            KnowledgeGraph
           + AST + behaviour         BehaviourTracker
```

---

## Component Responsibilities

### `tools/` — Single Source of Truth

All MCP tools are implemented here. MCP server, FastAPI, and gRPC are thin adapters that
forward requests to these functions. **Never duplicate logic in an adapter.**

| Module | Responsibility |
|--------|---------------|
| `tools/memory.py` | `retrieve_memory`, `store_memory`, `log_episode` |
| `tools/index.py` | `lookup_symbol`, `semantic_search_code` |
| `tools/graph.py` | `who_calls`, `subgraph`, `graph_stats`, `dependency_graph` |
| `tools/context.py` | `context_pack` — bundles all signals into token-bounded output |
| `tools/docs.py` | `search_docs` — full-text search over `.md` files |
| `tools/diff.py` | `explain_change` — explains what changed between code versions |

---

### `retrieval/hybrid.py` — Hybrid Retrieval

Combines four signals into a single ranked result list:

1. **FAISS vector similarity** — semantic embedding distance
2. **Knowledge graph distance** — hop count from query entity to candidate
3. **BM25 keyword relevance** — term frequency over the episodic corpus
4. **Behaviour weights** — frequency of past access patterns (via `BehaviourTracker`)

Do not call FAISS or the graph directly from tools — always go through `HybridRetriever`.

---

### `memory/` — Storage Layer

| Module | Responsibility |
|--------|---------------|
| `memory/vector_memory.py` | FAISS semantic store + sentence-transformer embeddings |
| `memory/episodic_memory.py` | Append-only event journal with BM25 search and stale marking |
| `memory/circuit_breaker.py` | RSS memory limit — opens circuit at threshold to prevent OOM |

---

### `graph/` — Knowledge Graph

| Module | Responsibility |
|--------|---------------|
| `graph/knowledge_graph.py` | NetworkX DiGraph: FILE, FUNCTION, CLASS, CONCEPT, QUERY nodes |
| `graph/behaviour_tracker.py` | Tracks access frequency per symbol; weights retrieval signals |

Node types:
- `FILE` — source file
- `FUNCTION` — function/method definition
- `CLASS` — class/struct/interface definition
- `CONCEPT` — abstract concept stored as memory
- `QUERY` — past query (links to relevant symbols)

Edge types:
- `CONTAINS` — FILE → FUNCTION/CLASS
- `CALLS` — FUNCTION → FUNCTION
- `USES` — FUNCTION/CLASS → CLASS
- `RELATED_TO` — CONCEPT → FUNCTION/CLASS

---

### `indexer/` — AST Indexing

| Module | Responsibility |
|--------|---------------|
| `indexer/ast_indexer.py` | Multi-language AST parser + symbol extractor + FAISS ingestion |
| `indexer/file_watcher.py` | Watchdog-based hot reload — indexes on file change, prunes on delete |

Supported languages: Python (stdlib `ast`), TypeScript, JavaScript, Go, Rust, Java, C++ (tree-sitter).

On file deletion, the watcher:
1. Removes FAISS vector IDs via `remove_ids()`
2. Calls `KnowledgeGraph.remove_file_nodes()` to clean the graph
3. Marks episodic entries as `stale=True` (never deletes history)

---

### `vector_db/` — Storage Adapter Layer

Pluggable vector storage backend:

| Class | Backend |
|-------|---------|
| `FAISSAdapter` | Default — FAISS flat index, no external dependency |
| `ChromaDBAdapter` | Optional — ChromaDB, requires `pip install chromadb` |

Configured via `storage.vector_backend` in `config.json`.
Use `get_storage_adapter()` factory — do not instantiate directly.

---

### `orchestrator/` — Multi-Model Routing

| Module | Responsibility |
|--------|---------------|
| `orchestrator/classifier.py` | Query complexity classifier — QUICK / DETAILED / COMPLEX |
| `orchestrator/router.py` | Routes QUICK to Gemini Flash, COMPLEX to Claude Opus, etc. |

Do not hardcode model names outside `classifier.py`.

---

### `api/` — REST Adapter (FastAPI)

JWT-authenticated REST API. Thin layer over `tools/`.

Key routes:
- `POST /auth/login` → returns JWT token
- `POST /memory/store` → `store_memory()`
- `POST /memory/retrieve` → `retrieve_memory()` (Redis-cached)
- `GET /graph/symbol/{name}` → `lookup_symbol()` (Redis-cached)
- `GET /graph/who-calls/{name}` → `who_calls()`
- `POST /graph/subgraph` → `subgraph()`

---

### `rpc/` — gRPC Adapter

Protocol Buffer streaming service for multi-agent communication.

Services defined in `rpc/proto/cognirepo.proto`:
- `QueryService.Query` — unary query
- `ContextService.StreamContext` — server-streaming context pack
- `QueryService.SubQueryStream` — client-stream of sub-queries

Run `make proto` to regenerate `cognirepo_pb2.py` after changing the `.proto` file.

---

### `cli/` — Command-Line Interface

Entry point: `cognirepo` → `cli/main.py::main()`

Key modules:
- `cli/init_project.py` — `cognirepo init` scaffolding, idempotent
- `cli/wizard.py` — interactive terminal wizard
- `cli/daemon.py` — heartbeat, singleton lock, systemd unit generation
- `cli/repl.py` — interactive REPL (when run with no args)
- `cli/seed.py` — seed behaviour graph from git history

---

## Data Flow: `context_pack("how does BM25 search work")`

```
tools/context.py::context_pack()
    │
    ├── HybridRetriever.retrieve(query, top_k=20)
    │       ├── VectorMemory.search(query)          → top FAISS hits
    │       ├── KnowledgeGraph.subgraph(entity)     → related nodes
    │       ├── EpisodicMemory.search_episodes()    → BM25 keyword hits
    │       └── BehaviourTracker.weight()           → access frequency boost
    │
    ├── ASTIndexer.lookup_symbol("BM25Okapi")       → file + line
    │
    └── Pack to max_tokens budget → return bundle
```

---

## Storage Isolation

All CogniRepo data is scoped to `.cognirepo/` in the project root.
Different projects never share data.

The `.cognirepo/` directory is listed in `.gitignore` — data is never committed.
