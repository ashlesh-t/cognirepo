# CogniRepo Architecture

---

## Package Layer Hierarchy (v2.0.0+)

Six dependency-ordered layers with downward-only coupling enforced by `scripts/check_circular_deps.py`:

```
Layer 0 — core/
    core/config/        configuration, paths, locking, org registry, versioning
    core/security/      encryption, storage config, project IDs
    core/vector_db/     FAISS/Chroma adapter factory (no business logic)
    core/_bm25/         BM25 pure-Python fallback + C++ extension
    core/probes.py      RSS + storage size probes (moved from cron/)
    core/metrics.py     Prometheus counters (moved from server/)

Layer 1 — data/
    data/memory/        semantic store, episodic journal, embeddings, circuit breaker
    data/graph/         knowledge graph, behaviour tracker, org graph

Layer 2 — intelligence/
    intelligence/indexer/     AST indexer, doc ingester, summarizer, file watcher
    intelligence/retrieval/   hybrid retriever, cross-repo router, docs search
    intelligence/orchestrator/ request classifier, context builder, model adapters

Layer 3 — interface/
    interface/tools/    MCP tool handlers (single entry point, stateless)
    interface/server/   FastMCP server, session listener, learning middleware
    interface/adapters/ OpenAI spec export, cursor MCP config

Layer 4 — ops/
    ops/cron/           scheduler, memory pruner

Layer 5 — interface/cli/  (top-level consumer, depends on all layers)
    cognirepo/          package stub enabling `python -m cognirepo`
```

**Dependency rule:** a module in layer N may only import from layers 0…N.
Upward imports (lower layer → higher layer) are forbidden at toplevel.
Lazy upward imports inside function bodies are permitted but logged by the checker.

**Enforcement:** `scripts/check_circular_deps.py` rebuilds the import graph at every commit and fails on any upward dependency.

---

## System Overview

![alt text](cognirepo-workflow.png)

---

## Component Responsibilities

### `interface/tools/` — Single Source of Truth

forward requests to these functions. **Never duplicate logic in an adapter.**

| Module | Responsibility |
|--------|---------------|
| `interface/tools/retrieve_memory.py` | `retrieve_memory`, `store_memory`, `log_episode` |
| `interface/tools/semantic_search_code.py` | `lookup_symbol`, `semantic_search_code` |
| `interface/tools/context_pack.py` | `context_pack` — bundles all signals into token-bounded output |
| `interface/tools/search_docs.py` | `search_docs` — full-text search over `.md` files |
| `interface/tools/explain_change.py` | `explain_change` — explains what changed between code versions |
| `interface/tools/dependency_graph.py` | `dependency_graph` — imports-from + imported-by via graph edges |

---

### `intelligence/retrieval/hybrid.py` — Hybrid Retrieval

Combines **3 signals** into a single weighted ranked result list:

1. **FAISS vector similarity** — semantic embedding distance (weight 0.5)
2. **Knowledge graph distance** — hop count from query entity to candidate (weight 0.3)
3. **Behaviour weights** — frequency of past access patterns via `BehaviourTracker` (weight 0.2)

Two additional components work alongside but are **not** blended into `final_score`:
- **AST pre-scorer** — expands the candidate pool before scoring (symbol lookup via `ASTIndexer`)
- **BM25 episodic side-channel** — searches the episodic event log separately; results are surfaced next to, not merged into, the ranked list. BM25 also acts as a full fallback retriever when FAISS embeddings are unavailable (circuit breaker open).

Do not call FAISS or the graph directly from tools — always go through `HybridRetriever`.

---

### `data/memory/` — Storage Layer

| Module | Responsibility |
|--------|---------------|
| `data/memory/semantic_memory.py` | FAISS semantic store + sentence-transformer embeddings |
| `data/memory/episodic_memory.py` | Append-only event journal with BM25 search and stale marking |
| `data/memory/circuit_breaker.py` | RSS memory limit — opens circuit at threshold to prevent OOM |

---

### `data/graph/` — Knowledge Graph

| Module | Responsibility |
|--------|---------------|
| `data/graph/knowledge_graph.py` | NetworkX DiGraph: FILE, FUNCTION, CLASS, CONCEPT, QUERY, SESSION, USER_ACTION, MEMORY nodes |
| `data/graph/behaviour_tracker.py` | Tracks access frequency per symbol; weights retrieval signals |

Node types (`NodeType` constants in `data/graph/knowledge_graph.py`):
- `FILE` — source file
- `FUNCTION` — function/method definition
- `CLASS` — class/struct/interface definition
- `CONCEPT` — abstract concept stored as memory
- `QUERY` — past query (links to relevant symbols)
- `SESSION` — a conversation session
- `USER_ACTION` — a recorded user interaction
- `MEMORY` — cross-agent memory node (synced from Claude/Gemini/etc.)

Edge types (`EdgeType` constants in `data/graph/knowledge_graph.py`):
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

### `intelligence/indexer/` — AST Indexing

| Module | Responsibility |
|--------|---------------|
| `intelligence/indexer/ast_indexer.py` | Multi-language AST parser + symbol extractor + FAISS ingestion |
| `intelligence/indexer/file_watcher.py` | Watchdog-based hot reload — indexes on file change, prunes on delete |

Supported languages: Python (stdlib `ast`), TypeScript, JavaScript, Go, Rust, Java, C++ (tree-sitter).

On file deletion, the watcher:
1. Removes FAISS vector IDs via `remove_ids()`
2. Calls `KnowledgeGraph.remove_file_nodes()` to clean the graph
3. Marks episodic entries as `stale=True` (never deletes history)

---

### `core/vector_db/` — Storage Adapter Layer

Pluggable vector storage backend:

| Class | Backend |
|-------|---------|
| `FAISSAdapter` | Default — FAISS flat index, no external dependency |
| `ChromaDBAdapter` | Optional — ChromaDB, requires `pip install chromadb` |

Configured via `storage.vector_backend` in `config.json`.
Use `get_storage_adapter()` factory (`core/vector_db/__init__.py`) — do not instantiate directly.

---

### `intelligence/orchestrator/` — Multi-Model Routing

| Module | Responsibility |
|--------|---------------|
| `intelligence/orchestrator/classifier.py` | Query complexity classifier — QUICK / STANDARD / COMPLEX / EXPERT |
| `intelligence/orchestrator/router.py` | Routes QUICK to Gemini Flash, COMPLEX to Claude Opus, etc. |

Do not hardcode model names outside `intelligence/orchestrator/classifier.py`.

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

### `interface/cli/` — Command-Line Interface

Entry point: `cognirepo` → `interface/cli/main.py::main()`

Key modules:
- `interface/cli/init_project.py` — `cognirepo init` scaffolding, idempotent
- `interface/cli/wizard.py` — interactive terminal wizard
- `interface/cli/daemon.py` — heartbeat, singleton lock, systemd unit generation
- `interface/cli/seed.py` — seed behaviour graph from git history

---

## Data Flow: `context_pack("how does BM25 search work")`

```
interface/tools/context_pack.py::context_pack()
    │
    ├── HybridRetriever.retrieve(query, top_k=20)   [intelligence/retrieval/hybrid.py]
    │       ├── VectorMemory.search(query)           → top FAISS hits
    │       ├── KnowledgeGraph.subgraph(entity)      → related nodes  [data/graph/]
    │       ├── EpisodicMemory.search_episodes()     → BM25 keyword hits  [data/memory/]
    │       └── BehaviourTracker.weight()            → access frequency boost
    │
    ├── ASTIndexer.lookup_symbol("BM25Okapi")        → file + line  [intelligence/indexer/]
    │
    └── Pack to max_tokens budget → return bundle
```

---

## Storage Isolation

All CogniRepo data is scoped to `.cognirepo/` in the project root.
Different projects never share data.

The `.cognirepo/` directory is listed in `.gitignore` — data is never committed.
