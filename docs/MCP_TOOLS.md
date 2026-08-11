# CogniRepo MCP Tools Reference

34 tools available via the MCP protocol. These are the functions Claude, Gemini, and Cursor can call.

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
  "query": "how does hybrid retrieval work",
  "status": "ok",
  "token_count": 1840,
  "sections": [
    {"type": "code", "source": "retrieval/hybrid.py", "score": 0.91, "content": "...", "bucket": "HIGH"}
  ],
  "truncated": false
}
```

`status` is always one of: `"ok"` | `"no_confident_match"` | `"index_empty"`.
When `status == "no_confident_match"` the response also includes `"best_score"` and `"suggestion"`.

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

**Signature:** `who_calls(function_name: str, repo_path: str = None) → dict`

Return all callers of a function in the knowledge graph. Use before refactoring.

**Input:**
```json
{ "function_name": "cache_get" }
```

**Output:**
```json
{
  "local_callers": [
    { "caller": "api/routes/memory.py::retrieve", "line": 28 },
    { "caller": "api/routes/graph.py::symbol_lookup", "line": 15 }
  ],
  "cross_repo_callers": [],
  "truncated": false
}
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

**Signature:** `retrieve_memory(query: str, top_k: int = 5, include_org: bool = False, repo_path: str | None = None) → list[dict]`

Semantic similarity search over stored memories. `include_org=True` also queries sibling
repositories in the same organization. `repo_path` targets a repository other than the
server's configured project directory.

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
{ "logged": true }
```

---

## graph_stats

**Signature:** `graph_stats() → dict`

Return node/edge count and health summary of the knowledge graph, plus index
freshness.

**Output:**
```json
{
  "node_count": 1243,
  "edge_count": 4871,
  "top_concepts": ["symbol::foo", "symbol::bar"],
  "last_indexed": "2026-07-22T18:20:10+00:00",
  "full_indexed_at": "2026-07-22T16:31:07+00:00",
  "index_age_minutes": 0,
  "index_stale": false,
  "stale_reindexing_triggered": false,
  "watcher_alive": true,
  "integrity": {
    "orphans": [],
    "dangling_files": [],
    "swept_at": "2026-07-31T12:00:00+00:00"
  }
}
```

**Freshness fields:**

| Field | Meaning |
|---|---|
| `last_indexed` | Timestamp of the most recent index write of *any* kind, including a watcher's single-file incremental save. Tracks the same event as `index_age_minutes`. |
| `full_indexed_at` | Timestamp of the last complete `index_repo()` sweep. Older than `last_indexed` whenever the watcher has applied incremental edits since. |
| `index_age_minutes` | Age of `ast_index.json` on disk. |
| `index_stale` | True when the index is older than 60 min, no watcher is live, and git HEAD has moved past the last indexed SHA. |
| `watcher_alive` | True when a watcher process (either the `cognirepo watch` daemon or the in-process auto-watcher `serve` starts) has refreshed its heartbeat within the last 120 s. |

Before COGNIREPO-D14, `last_indexed` only advanced on a full `index_repo()`
run, so a repo kept current by the watcher reported a hours-old
`last_indexed` next to `index_age_minutes: 0` — two clocks in one payload.

**Integrity fields (COGNIREPO-201):**

| Field | Meaning |
|---|---|
| `orphans` | FILE/FUNCTION/CLASS node IDs with degree 0 (no edges in or out). Excludes MEMORY/SESSION/ERROR/QUERY/CONCEPT nodes, which are legitimately edge-free early in their lifecycle. |
| `dangling_files` | File paths (FILE node IDs, or FUNCTION/CLASS nodes' `file` attr) that no longer exist on disk — left behind when a file is deleted while no watcher/server was running to catch it. |
| `swept_at` | ISO-8601 UTC timestamp of this integrity sweep — recomputed on every `graph_stats` call, O(nodes). |

`doctor` flags nonzero `orphans`/`dangling_files` as a warning with a repair hint.
`cognirepo graph repair [--apply]` prunes dangling file nodes (dry-run by default) —
see [USAGE.md](USAGE.md).

---

## episodic_search

**Signature:** `episodic_search(query: str, limit: int = 10, include_archived: bool = False) → list[dict]`

BM25-ranked keyword search in the event history; vector-similarity fallback when BM25
returns zero results. `include_archived` (COGNIREPO-205) also searches events rotated
out to `episodic_archive.json` by `episodic_max_events` rotation — default False (live
store only). Archived hits are tagged `{"archived": true}`.

**Input:**
```json
{ "query": "redis cache bug", "limit": 5, "include_archived": true }
```

**Output:**
```json
[
  { "event": "Fixed Redis cache encoding bug", "timestamp": "2026-04-02T12:30:00Z", "score": 3.8 }
]
```

---

## dependency_graph

**Signature:** `dependency_graph(module: str, direction: str = "both", depth: int = 2) → dict`

Return import/dependency graph for a specific module.

**Input:**
```json
{ "module": "retrieval/hybrid.py", "direction": "both", "depth": 2 }
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

**Signature:** `explain_change(target: str, since: str = "7d", max_commits: int = 10) → dict`

Explain recent git changes to a file or function using commit history and episodic memory.

**Input:**
```json
{ "target": "api/cache.py", "since": "30d" }
```

**Output:**
```json
{
  "target": "api/cache.py",
  "commits": [
    {"sha": "a1b2c3d", "message": "fix: Redis cache encoding", "author": "dev", "date": "2026-04-02"}
  ],
  "explanation": "Recent changes added Redis cache with JSON encoding fix and graceful degradation."
}
```

Returns `{"target": "...", "commits": [], "explanation": "No commits found."}` if no history exists — never crashes.

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

**Signature:** `org_wide_search(query: str, top_k: int = 5) → dict`

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

**Signature:** `link_repos(src: str, dst: str, relationship: str = "imports", note: str = "", src_service_type: str = None, src_port: int = None, src_api_base_url: str = None) → dict`

**When:** Call when you discover one repo imports from or calls another. relationship: `imports` | `calls_api` | `shares_schema` | `discovered` | `child_of`.

**Auto-detected edges:** `IMPORTS` only — CogniRepo scans pyproject.toml, package.json, go.mod, Cargo.toml, requirements.txt and creates IMPORTS edges automatically.
**Manual-only edges:** `CALLS_API` and `SHARES_SCHEMA` must be declared explicitly via this tool. There is no automatic HTTP-call or schema detection.

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

**Signature:** `record_user_preference(preference_key: str, preference_value: str, context: str = "", repo_path: str = None) → dict`

**When:** Call IMMEDIATELY when user says "I prefer...", "always use...", "never do...", or states any explicit preference. Stored permanently; surfaced by `get_user_profile()` under `explicit_preferences`.

**Input:**
```json
{"key": "response_style", "value": "concise"}
```
**Output:**
```json
{"key": "response_style", "value": "concise", "recorded": true}
```

---

## get_agent_bootstrap

**Signature:** `get_agent_bootstrap(repo_path: str = None) → dict`

**When:** Call ONCE at session start instead of the 4-call sequence (get_session_brief → get_last_context → get_user_profile → get_error_patterns). Returns ~300 tokens vs ~900 tokens.

**Input:**
```json
{}
```
**Output:**
```json
{
  "repo": "cognirepo",
  "architecture": "CogniRepo: FAISS + graph + AST + MCP. Tools in tools/, retrieval via retrieval/hybrid.py...",
  "hot_symbols": ["hybrid_retrieve:retrieval/hybrid.py:45", "context_pack:tools/context_pack.py:12"],
  "last_focus": {"files": ["retrieval/hybrid.py"], "query": "how does scoring work", "agent": "claude"},
  "framing": {"depth": "detailed", "vocabulary": ["retrieval", "faiss", "hybrid"], "hints": "prefers detailed responses; often asks 'how' questions; domain vocabulary: retrieval, faiss, hybrid"},
  "error_patterns": [{"type": "OOM", "count": 2, "prevention_hint": "Check RSS before loading large index"}],
  "index_health": {"symbols": 1240, "files": 92, "status": "ok"},
  "recent_timeline": [
    {"ts": "2026-08-08T09:00:00+00:00", "kind": "decision", "summary": "use FAISS for vector search", "ref": "e_42"},
    {"ts": "2026-08-07T14:00:00+00:00", "kind": "error", "summary": "ImportError (x3)", "ref": "ImportError"},
    {"ts": "2026-08-06T11:00:00+00:00", "kind": "session", "summary": "how does scoring work", "ref": "sess_abc123"}
  ],
  "decision_nudge": "no decisions recorded yet — use record_decision for architectural choices"
}
```

**recent_timeline** (COGNIREPO-204): last 5 entries from the past 7 days, merged
chronologically across sessions, episodes, decisions, and errors — replaces the
`get_session_history` + `episodic_search` + `get_error_patterns` 3-call stitch for a
quick "what happened recently" view. Folded into this tool's existing output rather
than a new MCP tool (0 manifest tokens vs. ~180 measured for a standalone
`get_timeline` tool). For the full query surface (`since`/`include_archived`/`limit`,
plus the deterministic `rollup()` — counts + top decisions/errors, no model-generated
text), call `data.memory.timeline.merge()`/`rollup()` directly, or from a future
`generate_insights` tool (EPIC-300).

**decision_nudge** (COGNIREPO-205): present only when the last 30 days have ≥5
episodes but 0 decisions — a hint to use `record_decision` for architectural
choices, since CLAUDE.md's instruction alone doesn't guarantee agents call it.
Omitted from the payload entirely when there's nothing to nudge about.

**Episodic events also include `index_event`-typed entries** (COGNIREPO-205):
`cognirepo index-repo` and `cognirepo org rewire` completions are logged
automatically (metadata `{"type": "index_event", ...}` with symbol/file or
edge/repo counts), so infrastructure activity shows up in `recent_timeline` /
`data.memory.timeline.merge()` even when no agent called `log_episode`.

---

## supersede_learning

**Signature:** `supersede_learning(old_id: str, new_text: str, learning_type: str = "fact", repo_path: str = None) → dict`

**When:** Call when `store_memory` returns a `conflicts` list with an outdated/incorrect entry. Deprecates the old entry and replaces it with corrected text. Prevents conflicting memories from co-existing.

**Input:**
```json
{"old_id": "abc123", "new_text": "fastembed embed() returns a generator, use next(iter(...))", "learning_type": "fact"}
```
**Output:**
```json
{"found_old": true, "new_id": "def456"}
```

---

## find_symbol_path

**Signature:** `find_symbol_path(from_symbol: str, to_symbol: str, from_repo: str = "", to_repo: str = "") → dict`

**When:** Trace the shortest call-graph path between two symbols, crossing service boundaries via the org graph when needed. Uses weighted Dijkstra (core entry-point symbols preferred over indirect hops; cross-service org edges cost more).

**Input:**
```json
{ "from_symbol": "handleTransfer", "to_symbol": "settleNpci", "from_repo": "/projects/bank-service" }
```
**Output:**
```json
{ "path": ["bank-service::handleTransfer", "npci-service::settle"], "hops": 2, "crosses_services": true, "services_traversed": ["bank-service", "npci-service"] }
```
Returns `{error: ...}` when no path exists.

---

## get_service_endpoints

**Signature:** `get_service_endpoints(repo_path: str = "") → dict`

**When:** List the HTTP endpoint registry for a service (from `endpoints.json`, populated by `cognirepo index-repo`). Each entry includes method, path pattern, handler function, file, and framework.

**Input:**
```json
{ "repo_path": "/projects/bank-service" }
```
**Output:**
```json
{ "endpoints": [{"method": "POST", "path": "/api/transfer", "handler": "handleTransfer", "framework": "spring"}], "count": 1, "repo": "bank-service" }
```

---

## architecture_overview

**Signature:** `architecture_overview(scope: str = "root", repo_path: str = None) → str`

**When:** Call for a human-readable summary of the repo, a directory, or a specific file. Returns pre-computed summaries from `summaries.json` — fast, no embedding needed. Run `cognirepo summarize` first to populate.

scope: `"root"` for full repo summary, a directory path like `"tools"`, or a file path like `"retrieval/hybrid.py"`.

**Input:**
```json
{"scope": "root"}
```
**Output:**
```
Repository: cognirepo
  92 source files | 1240 symbols
  Top packages: tools, retrieval, memory, graph, indexer
  Key classes: HybridRetriever, ASTIndexer, KnowledgeGraph, BehaviourTracker
  Key functions: hybrid_retrieve, context_pack, lookup_symbol, store_memory
```

---

## org_search

**Signature:** `org_search(query: str, top_k: int = 5) → list`

**⚠ DEPRECATED** — use `org_wide_search` instead. Text-match fallback search across org repos. Only call when `org_wide_search` returns empty results.

**Input:**
```json
{"query": "authentication flow"}
```
**Output:**
```json
[{"text": "...", "source_repo": "auth-service", "score": 0.72}]
```

