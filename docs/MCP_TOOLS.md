# CogniRepo MCP Tools Reference

Every tool available via the MCP protocol. These are the functions Claude, Gemini, and Cursor can call.

---

## context_pack

**Signature:** `context_pack(query: str, max_tokens: int = 2000) → dict`

Bundle the most relevant code, episodic history, and graph context into a token-bounded block.
Call this **before reading any source file**.

**Input:**
```json
{ "query": "how does hybrid retrieval work", "max_tokens": 2000 }
```

**Output:**
```json
{
  "code_snippets": [{"file": "retrieval/hybrid.py", "lines": "1-50", "content": "..."}],
  "episodic_hits": [{"event": "Fixed BM25 ranking bug", "timestamp": "2026-03-30"}],
  "graph_context": "HybridRetriever → FAISSAdapter, KnowledgeGraph",
  "tokens_used": 1840
}
```

---

## lookup_symbol

**Signature:** `lookup_symbol(name: str) → list[dict]`

Find where a function, class, or variable is defined. O(1) LRU-cached reverse index.

**Input:**
```json
{ "name": "retrieve_memory" }
```

**Output:**
```json
[
  { "file": "tools/memory.py", "line": 42, "type": "FUNCTION", "language": "python" }
]
```

---

## who_calls

**Signature:** `who_calls(function_name: str) → list[dict]`

Return all callers of a function in the knowledge graph. Use before refactoring.

**Input:**
```json
{ "function_name": "cache_get" }
```

**Output:**
```json
[
  { "caller": "api/routes/memory.py::retrieve", "line": 28 },
  { "caller": "api/routes/graph.py::symbol_lookup", "line": 15 }
]
```

---

## subgraph

**Signature:** `subgraph(entity: str, depth: int = 1) → dict`

Return the local knowledge graph neighbourhood around an entity.

**Input:**
```json
{ "entity": "HybridRetriever", "depth": 2 }
```

**Output:**
```json
{
  "nodes": ["HybridRetriever", "FAISSAdapter", "KnowledgeGraph", "BehaviourTracker"],
  "edges": [
    {"from": "HybridRetriever", "to": "FAISSAdapter", "type": "USES"},
    {"from": "HybridRetriever", "to": "KnowledgeGraph", "type": "USES"}
  ]
}
```

---

## retrieve_memory

**Signature:** `retrieve_memory(query: str, top_k: int = 5) → list[dict]`

Semantic similarity search over stored memories.

**Input:**
```json
{ "query": "how we fixed the BM25 ranking issue", "top_k": 3 }
```

**Output:**
```json
[
  {
    "text": "Fixed BM25 ranking — root cause was corpus not rebuilding on save()",
    "source": "debug",
    "importance": 0.91
  }
]
```

---

## search_docs

**Signature:** `search_docs(query: str) → list[dict]`

Full-text search across all `.md` documentation files with snippets.

**Input:**
```json
{ "query": "how to add a new language" }
```

**Output:**
```json
[
  {
    "file": "LANGUAGES.md",
    "line": 14,
    "snippet": "## Adding a new language\n1. Create `language_grammars/<lang>.py`..."
  }
]
```

---

## store_memory

**Signature:** `store_memory(text: str, source: str = "") → dict`

Persist a memory to the FAISS semantic index. Call this after fixing a bug or making a decision.

**Input:**
```json
{ "text": "Fixed: Redis cache_set was not encoding values as JSON", "source": "debug" }
```

**Output:**
```json
{ "status": "stored", "id": "mem_a3f2c9" }
```

---

## log_episode

**Signature:** `log_episode(event: str, metadata: dict = {}) → dict`

Record a significant event to the append-only episodic log.

**Input:**
```json
{
  "event": "Completed Sprint 5 — Redis caching, Cursor/VS Code MCP, proto CI guard",
  "metadata": { "sprint": 5, "tasks": ["TASK-014", "TASK-015", "TASK-016"] }
}
```

**Output:**
```json
{ "status": "logged", "timestamp": "2026-04-03T18:00:00Z" }
```

---

## graph_stats

**Signature:** `graph_stats() → dict`

Return node/edge count and health summary of the knowledge graph.

**Output:**
```json
{
  "nodes": 1243,
  "edges": 4871,
  "node_types": { "FUNCTION": 892, "CLASS": 201, "FILE": 150 },
  "healthy": true
}
```

---

## episodic_search

**Signature:** `episodic_search(query: str, limit: int = 10) → list[dict]`

BM25-ranked keyword search in the event history.

**Input:**
```json
{ "query": "redis cache bug", "limit": 5 }
```

**Output:**
```json
[
  { "event": "Fixed Redis cache encoding bug", "timestamp": "2026-04-02T12:30:00Z", "score": 3.8 }
]
```

---

## dependency_graph

**Signature:** `dependency_graph(file_path: str) → dict`

Return import/dependency graph for a specific file.

**Input:**
```json
{ "file_path": "retrieval/hybrid.py" }
```

**Output:**
```json
{
  "imports": ["vector_db.faiss", "graph.knowledge_graph", "memory.episodic_memory"],
  "imported_by": ["tools/memory.py", "api/routes/memory.py"]
}
```

---

## semantic_search_code

**Signature:** `semantic_search_code(query: str, language: str = "", top_k: int = 5) → list[dict]`

Semantic search over indexed code symbols.

**Input:**
```json
{ "query": "function that searches episodic memory by BM25", "language": "python", "top_k": 3 }
```

**Output:**
```json
[
  { "file": "memory/episodic_memory.py", "symbol": "search_episodes", "line": 120, "score": 0.89 }
]
```

---

## explain_change

**Signature:** `explain_change(file_path: str, before: str, after: str) → dict`

Explain what changed between two code versions.

**Input:**
```json
{
  "file_path": "api/cache.py",
  "before": "def cache_get(key): return None",
  "after": "def cache_get(key): ..."
}
```

**Output:**
```json
{
  "summary": "Added Redis lookup with graceful degradation on connection failure",
  "impact": ["api/routes/memory.py", "api/routes/graph.py"]
}
```
