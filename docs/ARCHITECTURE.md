# CogniRepo Architecture

---

## System Overview

![alt text](cognirepo-workflow.png)

---

## Component Responsibilities

### `tools/` — Single Source of Truth

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

Combines **3 signals** into a single weighted ranked result list:

1. **FAISS vector similarity** — semantic embedding distance (weight 0.5)
2. **Knowledge graph distance** — hop count from query entity to candidate (weight 0.3)
3. **Behaviour weights** — frequency of past access patterns via `BehaviourTracker` (weight 0.2)

Two additional components work alongside but are **not** blended into `final_score`:
- **AST pre-scorer** — expands the candidate pool before scoring (symbol lookup via `ASTIndexer`)
- **BM25 episodic side-channel** — searches the episodic event log separately; results are surfaced next to, not merged into, the ranked list. BM25 also acts as a full fallback retriever when FAISS embeddings are unavailable (circuit breaker open).

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
| `graph/knowledge_graph.py` | NetworkX DiGraph: FILE, FUNCTION, CLASS, CONCEPT, QUERY, SESSION, USER_ACTION, MEMORY nodes |
| `graph/behaviour_tracker.py` | Tracks access frequency per symbol; weights retrieval signals |

Node types (`NodeType` constants in `graph/knowledge_graph.py`):
- `FILE` — source file
- `FUNCTION` — function/method definition
- `CLASS` — class/struct/interface definition
- `CONCEPT` — abstract concept stored as memory
- `QUERY` — past query (links to relevant symbols)
- `SESSION` — a conversation session
- `USER_ACTION` — a recorded user interaction
- `MEMORY` — cross-agent memory node (synced from Claude/Gemini/etc.)

Edge types (`EdgeType` constants in `graph/knowledge_graph.py`):
- `RELATES_TO` — generic semantic relationship between two nodes
- `DEFINED_IN` — FUNCTION/CLASS → FILE (symbol defined in file)
- `CALLED_BY` — FUNCTION → FUNCTION (callee → caller, forward direction)
- `CALLS` — FUNCTION → FUNCTION (internal reverse edge; enables BFS without `predecessors()`)
- `QUERIED_WITH` — CONCEPT → QUERY (concept was mentioned in a query)
- `CO_OCCURS` — FILE ↔ FILE (frequently edited together)
- `IMPORTS` — FILE → FILE (file A imports file B)
- `INHERITS` — CLASS → CLASS (class A inherits from class B)
- `EXPOSES` — FUNCTION → ENDPOINT (function handles an HTTP route)
- `CALLS_ENDPOINT` — FUNCTION → ENDPOINT (function calls a remote service endpoint)

See `docs/architecture/graph.md` for the full schema with query examples.

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
| `orchestrator/classifier.py` | Query complexity classifier — QUICK / STANDARD / COMPLEX / EXPERT |
| `orchestrator/router.py` | Routes QUICK to Gemini Flash, COMPLEX to Claude Opus, etc. |

Do not hardcode model names outside `classifier.py`.

---



Key routes:
- `POST /auth/login` → returns JWT token
- `POST /memory/store` → `store_memory()`
- `POST /memory/retrieve` → `retrieve_memory()` (Redis-cached)
- `GET /graph/symbol/{name}` → `lookup_symbol()` (Redis-cached)
- `GET /graph/who-calls/{name}` → `who_calls()`
- `POST /graph/subgraph` → `subgraph()`

---


Protocol Buffer streaming service for multi-agent communication.

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
