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

---

## cross_repo_search

**Signature:** `cross_repo_search(query: str, scope: str = "project", top_k: int = 5) → dict`

Search knowledge from sibling repositories in the same org or project.

`scope="project"` — only repos in same project (recommended, high relevance).
`scope="org"` — all repos in organization (broader, use sparingly).

**When to call:**
- `lookup_symbol` returned empty and the symbol may live in a sibling repo
- Architecture question spans multiple services in the same project
- User asks "how does X work across the system"
- Importing from a sibling repo and need context on its internals

Call `list_org_context()` first to verify siblings exist before calling this.

**Input:**
```json
{ "query": "authentication flow", "scope": "project", "top_k": 5 }
```

**Output:**
```json
{
  "scope": "project",
  "query": "authentication flow",
  "results": [{"text": "...", "source": "repo_a", "importance": 0.8}],
  "result_count": 3,
  "repos_searched": ["auth-service", "api-gateway"]
}
```

---

## list_org_context

**Signature:** `list_org_context() → dict`

Returns org/project membership and sibling repos for the current repository.

**When to call:** FIRST when user asks about other services, related repos, cross-service behavior, or architecture spanning multiple codebases. Use the result to decide whether `cross_repo_search()` is worthwhile.

**Output:**
```json
{
  "org": "my-company",
  "project": "backend",
  "sibling_repos": ["/abs/path/auth-service"],
  "project_repos": ["/abs/path/api", "/abs/path/auth-service"]
}
```

---

## org_wide_search *(replaces deprecated `org_search`)*

**Signature:** `org_wide_search(query: str, top_k: int = 5) → list`

Search memories across ALL repositories in the organization. Prefer `cross_repo_search(scope="project")` for project-scoped queries.

`org_search` is a backward-compat alias — prefer `org_wide_search` in new integrations.

---

## record_decision

**Signature:** `record_decision(summary: str, rationale: str = "", affected_files: list = [], repo_path: str = None) → dict`

**When:** Call when a non-obvious architectural or implementation decision is made — when the WHY is not evident from the code. Do NOT call for routine changes.

**Input:**
```json
{"summary": "switched from REST to gRPC for auth service", "rationale": "latency target <5ms", "affected_files": ["auth/server.py"]}
```
**Output:**
```json
{"stored": true, "searchable_via": "episodic_search"}
```

---

## link_repos

**Signature:** `link_repos(src_repo: str, dst_repo: str, relationship: str = "imports", note: str = "", service_type: str = "", port: int = 0, api_base_url: str = "") → dict`

**When:** Call when you discover one repo imports from or calls another. relationship: `imports` | `calls_api` | `shares_schema` | `discovered` | `child_of`.

**Input:**
```json
{"src_repo": "/projects/api", "dst_repo": "/projects/auth", "relationship": "calls_api", "service_type": "rest_api", "port": 8001}
```
**Output:**
```json
{"linked": true, "edge": {"src": "/projects/api", "dst": "/projects/auth", "kind": "CALLS_API"}}
```

---

## org_dependencies

**Signature:** `org_dependencies(depth: int = 2) → dict`

**When:** Call to get a visual map of all registered repos and their dependency edges. Use before `cross_repo_traverse` to understand the graph shape.

**Input:**
```json
{"depth": 2}
```
**Output:**
```json
{"repos": [...], "edges": [...], "depth": 2}
```

---

## cross_repo_traverse

**Signature:** `cross_repo_traverse(symbol: str = None, start_repo: str = None, direction: str = "both", depth: int = 2) → dict`

**When:** Tracing a symbol, bug, or API change across service boundaries. direction: `dependencies` | `dependents` | `both`.

**Input:**
```json
{"symbol": "authenticate", "start_repo": "/projects/api", "direction": "dependents"}
```
**Output:**
```json
{"start_repo": "...", "dependencies": [...], "dependents": [...]}
```

---

## search_token

**Signature:** `search_token(token: str, repo_path: str = None) → list`

**When:** Exact token/string search across all indexed file names, symbol names, and docstrings. Unlike `lookup_symbol` (AST-defined symbols only), `search_token` matches any occurrence of the string.

**Input:**
```json
{"token": "MAX_RETRIES"}
```
**Output:**
```json
[{"file": "config.py", "line": 12, "match": "MAX_RETRIES = 3"}]
```

---

## get_session_brief

**Signature:** `get_session_brief(repo_path: str = None) → dict`

**When:** ALWAYS call at session start (step 1). Returns architecture summary, hot symbols, index health, and recent decisions.

**Output:**
```json
{"architecture": "...", "hot_symbols": [...], "index_health": {...}, "recent_decisions": [...]}
```

---

## get_last_context

**Signature:** `get_last_context(repo_path: str = None) → dict`

**When:** ALWAYS call at session start (step 2). Returns what the last agent (Claude/Gemini/Cursor) was looking at. Enables cross-agent handoff.

**Output:**
```json
{"query": "last context_pack query", "sections": [...], "token_count": 1842}
```

---

## get_session_history

**Signature:** `get_session_history(limit: int = 20, repo_path: str = None) → list`

**When:** Call to see recent session events in chronological order. Useful for understanding what happened in the last few sessions.

**Output:**
```json
[{"session_id": "...", "timestamp": "...", "event": "..."}]
```

---

## get_user_profile

**Signature:** `get_user_profile(repo_path: str = None) → dict`

**When:** ALWAYS call at session start (step 3). Apply `framing_hints` to ALL responses. Shows depth preference, domain vocabulary, code-focus %, and explicit stored preferences.

**Output:**
```json
{
  "depth_preference": "concise",
  "framing_hints": "prefers concise responses; focuses on code/symbols",
  "top_terminology": ["context_pack", "graph", "episodic"],
  "explicit_preferences": {"response_style": "concise"},
  "total_queries_tracked": 47
}
```

---

## get_error_patterns

**Signature:** `get_error_patterns(min_count: int = 1, repo_path: str = None) → list`

**When:** ALWAYS call at session start (step 4) and before proposing a fix. Returns recurring errors with prevention hints so Claude avoids repeating past mistakes.

**Output:**
```json
[{"error_type": "ImportError", "count": 3, "prevention_hint": "verify package installed", "last_seen": "..."}]
```

---

## record_error

**Signature:** `record_error(error_type: str, message: str = "", file_path: str = "", query_context: str = "", repo_path: str = None) → dict`

**When:** Call whenever Claude or the user hits an error. Builds the error pattern database that `get_error_patterns` reads.

**Input:**
```json
{"error_type": "TypeError", "message": "expected str got int", "file_path": "api/routes.py"}
```
**Output:**
```json
{"recorded": true, "error_type": "TypeError", "prevention_hint": "Wrong type — validate inputs at function boundary."}
```

---

## record_user_preference

**Signature:** `record_user_preference(key: str, value: str, repo_path: str = None) → dict`

**When:** Call IMMEDIATELY when user says "I prefer...", "always use...", "never do...", or states any explicit preference. Stored permanently; surfaced by `get_user_profile()` under `explicit_preferences`.

**Input:**
```json
{"key": "response_style", "value": "concise"}
```
**Output:**
```json
{"key": "response_style", "value": "concise", "recorded": true}
```

