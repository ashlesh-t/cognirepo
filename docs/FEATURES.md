# CogniRepo — Feature Inventory

> Audited against the codebase at commit HEAD (development branch).
> Status: ✅ Fully implemented · ⚠️ Partial/limited · 🔲 Stub/planned

---

## 1. MCP Tools (via `interface/server/mcp_server.py`)

All tools are registered via `FastMCP` and exposed over stdio transport.

| Tool | Status | Implementation | Notes |
|------|--------|----------------|-------|
| `context_pack(query, max_tokens)` | ✅ | `interface/tools/context_pack.py` | Hybrid retrieve → ±25-line code windows → greedy token pack; tiktoken + fallback |
| `lookup_symbol(name)` | ✅ | `interface/server/mcp_server.py` → `ASTIndexer.lookup_symbol()` | O(1) reverse index; enriched with graph node type |
| `who_calls(function_name)` | ✅ | `interface/server/mcp_server.py` → `KnowledgeGraph.get_neighbours()` | Returns callers + file/line from CALLED_BY edges |
| `subgraph(entity, depth)` | ✅ | `interface/server/mcp_server.py` → `KnowledgeGraph.subgraph_around()` | BFS up to depth 2; returns nodes + edge list |
| `retrieve_memory(query, top_k)` | ✅ | `interface/tools/retrieve_memory.py` | FAISS cosine similarity via `SemanticMemory.retrieve()` |
| `store_memory(text, source)` | ✅ | `interface/tools/store_memory.py` | Embeds + stores to FAISS; logs to episodic |
| `log_episode(event, metadata)` | ✅ | `data/memory/episodic_memory.py::log_event()` | Append-only JSONL with timestamp chain |
| `search_docs(query)` | ✅ | `intelligence/retrieval/docs_search.py` | Full-text search over all `.md` files, returns file+line+snippet |
| `episodic_search(query, limit)` | ✅ | `data/memory/episodic_memory.py::search_episodes()` | BM25Okapi ranked; module-level corpus cache with TTL |
| `graph_stats()` | ✅ | `interface/server/mcp_server.py` → `KnowledgeGraph.stats()` | Node count by type, edge count |
| `semantic_search_code(query, language, top_k)` | ✅ | `interface/tools/semantic_search_code.py` | FAISS search filtered to code-type entries; language filter optional |
| `dependency_graph(file_path)` | ✅ | `interface/tools/dependency_graph.py` | Returns imports-from + imported-by using knowledge graph edges |
| `explain_change(file_path, before, after)` | ✅ | `interface/tools/explain_change.py` | Diff analysis using `difflib`; identifies added/removed symbols |

**MCP transport:** stdio (FastMCP). No HTTP transport for MCP.

---

## 2. Memory Systems

### 2.1 Semantic Memory (FAISS)
| Feature | Status | File |
|---------|--------|------|
| Store text with embedding | ✅ | `data/memory/semantic_memory.py::store()` |
| FAISS flat index (L2) | ✅ | `core/vector_db/local_vector_db.py` |
| Cosine similarity retrieval | ✅ | `data/memory/semantic_memory.py::retrieve()` |
| Importance score (sentence length heuristic) | ✅ | `semantic_memory.py::compute_importance()` |
| Persist to disk (`index.faiss` + `metadata.json`) | ✅ | `core/vector_db/local_vector_db.py::save()` |
| Encryption at rest (AES-256 GCM) | ✅ | `core/security/encryption.py` + keyring; activated by `storage.encrypt: true` |
| Remove vectors by ID (`remove_ids`) | ✅ | `core/vector_db/local_vector_db.py` via `IndexIDMap2` |
| StorageAdapter ABC | ✅ | `core/vector_db/adapter.py` |
| FAISSAdapter | ✅ | `core/vector_db/faiss_adapter.py` |
| ChromaDBAdapter (optional) | ⚠️ | `core/vector_db/chroma_adapter.py` — guarded ImportError; requires `pip install chromadb` |
| Adapter factory (`get_storage_adapter`) | ✅ | `core/vector_db/__init__.py` |

### 2.2 Episodic Memory (Event Log)
| Feature | Status | File |
|---------|--------|------|
| Append-only JSONL event log | ✅ | `data/memory/episodic_memory.py` |
| Timestamp chain | ✅ | Each event has `timestamp` (ISO 8601) |
| BM25 keyword search (`search_episodes`) | ✅ | `_bm25` module with `BM25Okapi`; pure-Python fallback |
| Module-level BM25 corpus cache (TTL) | ✅ | `_BM25_INDEX` + `_BM25_TS` with 60s TTL |
| `mark_stale(file_path)` | ✅ | Tags events with `stale=True` when source file deleted |
| `get_history(limit)` | ✅ | Returns last N events |
| Cross-session persistence | ✅ | JSONL appended on disk; survives restarts |

### 2.3 Circuit Breaker
| Feature | Status | File |
|---------|--------|------|
| RSS memory limit | ✅ | `data/memory/circuit_breaker.py` |
| Open/closed/half-open states | ✅ | `CircuitBreaker.state` |
| Integration with retrieval | ✅ | `intelligence/retrieval/hybrid.py` checks breaker |

---

## 3. Knowledge Graph

**Backend:** NetworkX DiGraph (`data/graph/knowledge_graph.py`)

| Feature | Status | Notes |
|---------|--------|-------|
| Node types: FILE, FUNCTION, CLASS, CONCEPT, QUERY | ✅ | `NodeType` constants |
| Edge types: RELATES_TO, DEFINED_IN, CALLED_BY, QUERIED_WITH, CO_OCCURS | ✅ | `EdgeType` constants in `data/graph/knowledge_graph.py` |
| Persist/load (`graph.pkl`) | ✅ | Pickle serialization |
| `add_node()`, `add_edge()` | ✅ | |
| `nodes_for_file()` | ✅ | All nodes attributed to a file |
| `remove_file_nodes()` | ✅ | Removes FILE + symbol nodes; returns removed list |
| `get_neighbours(node, edge_types, direction)` | ✅ | Inbound/outbound filter |
| `hop_distance(src, dst)` | ✅ | BFS shortest path length |
| `shortest_path(src, dst)` | ✅ | Returns node list |
| `subgraph_around(node, radius)` | ✅ | BFS to radius; returns dict of nodes+edges |
| `stats()` | ✅ | Count by node type + total edges |
| Behaviour tracking | ✅ | `data/graph/behaviour_tracker.py` — access frequency per node |
| Entity extraction from text | ✅ | `data/graph/graph_utils.py::extract_entities_from_text()` |

---

## 4. AST Indexer

**File:** `intelligence/indexer/ast_indexer.py` + `intelligence/indexer/language_registry.py`

### Languages
| Language | Extensions | Backend | Status |
|----------|-----------|---------|--------|
| Python | `.py` | stdlib `ast` (always available) | ✅ |
| TypeScript | `.ts`, `.tsx` | tree-sitter-typescript | ✅ (if installed) |
| JavaScript | `.js`, `.jsx` | tree-sitter-javascript | ✅ (if installed) |
| Go | `.go` | tree-sitter-go | ✅ (if installed) |
| Rust | `.rs` | tree-sitter-rust | ✅ (if installed) |
| Java | `.java` | tree-sitter-java | ✅ (if installed) |
| C++ | `.cpp`, `.cc`, `.h`, `.hpp` | tree-sitter-cpp | ✅ (if installed) |

### Indexer Features
| Feature | Status | Notes |
|---------|--------|-------|
| Symbol extraction (functions, classes, variables) | ✅ | Per language via tree-sitter queries or ast.walk |
| Reverse index (symbol → file:line) | ✅ | `ASTIndexer.reverse_index` dict |
| `lookup_symbol(name)` — O(1) LRU cached | ✅ | LRU cache of size 512 |
| SHA-256 file hash cache (skip unchanged files) | ✅ | `ASTIndexer.sha256_cache` |
| `index_repo(path)` — recursive walk | ✅ | Returns summary dict with file/symbol counts |
| Persist/load index to disk | ✅ | JSON files in `.cognirepo/index/` |
| Call edge extraction | ✅ | Function call relationships added to KnowledgeGraph |
| Unsupported extension skip | ✅ | Graceful skip with counter |
| Ingest to FAISS | ✅ | Each symbol → embedding → LocalVectorDB |

---

## 5. File Watcher (Hot Reload)

**File:** `intelligence/indexer/file_watcher.py`

| Feature | Status | Notes |
|---------|--------|-------|
| Watchdog-based file monitoring | ✅ | `watchdog` library |
| Re-index on file modify/create | ✅ | `_handle_modified()` |
| Remove stale data on file delete | ✅ | `_remove()` — cleans FAISS, graph, marks episodic stale |
| Handle file rename | ✅ | Delete old + create new |
| Debouncing (avoid double-index) | ✅ | 0.5s settle time per file |
| KnowledgeGraph cleanup on delete | ✅ | `remove_file_nodes()` |
| FAISS vector removal on delete | ✅ | `remove_ids()` via stored chunk IDs |
| Rebuild reverse index after deletion | ✅ | `_rebuild_reverse_index()` |

---

## 6. Daemon & Process Management

**File:** `cli/daemon.py`

| Feature | Status | Notes |
|---------|--------|-------|
| Fork to background (`daemonize`) | ✅ | Double-fork UNIX daemon pattern |
| PID file management | ✅ | `.cognirepo/watchers/<pid>.json` |
| Singleton enforcement via `flock` | ✅ | `flock_register_watcher()` — prevents duplicate watchers |
| Stale-PID detection | ✅ | `_is_alive(pid)` check before claiming slot |
| Heartbeat file (30s interval) | ✅ | `write_heartbeat()` + background thread |
| `heartbeat_age_seconds()` | ✅ | Used by `cognirepo doctor` |
| Crash-recovery loop | ✅ | `run_watcher_with_crash_guard()` — restarts on crash |
| Systemd unit file generation | ✅ | `generate_systemd_unit()` / `write_systemd_unit()` |
| `cognirepo list` — list running daemons | ✅ | `list_watchers()` |
| `cognirepo list --stop` | ✅ | SIGTERM to selected daemon |
| `cognirepo list --view` | ✅ | Interactive log tail |

---

## 7. CLI Commands

**Entry point:** `cognirepo` → `cli/main.py`

| Command | Status | Notes |
|---------|--------|-------|
| `cognirepo init` | ✅ | Wizard or non-interactive; idempotent; prompts for index/watcher/systemd |
| `cognirepo init --non-interactive` | ✅ | Uses all defaults; no prompts |
| `cognirepo index-repo [path]` | ✅ | AST index + FAISS ingest + graph build |
| `cognirepo serve` | ✅ | MCP stdio server |
| `cognirepo watch` | ✅ | File watcher (foreground or daemon) |
| `cognirepo watch --ensure-running` | ✅ | Start if heartbeat stale |
| `cognirepo store-memory <text>` | ✅ | Direct memory storage |
| `cognirepo retrieve-memory <query>` | ✅ | Direct memory retrieval |
| `cognirepo search-docs <query>` | ✅ | Doc search |
| `cognirepo history` | ✅ | Episodic history |
| `cognirepo log-episode <event>` | ✅ | Log an event |
| `cognirepo doctor` | ✅ | Health check (10+ checks including daemon, BM25, API keys, language grammars) |
| `cognirepo doctor --verbose` | ✅ | Shows optional component checks |
| `cognirepo prune` | ✅ | Remove low-importance memories |
| `cognirepo prune --dry-run` | ✅ | Preview what would be pruned |
| `cognirepo list` | ✅ | Daemon management |
| `cognirepo export-spec` | ✅ | Export OpenAI-compatible tool spec |
| `cognirepo wait-api` | ✅ | Poll until REST API is ready |
| Interactive REPL (no args) | ✅ | `cli/repl.py` — routes to `orchestrator/router.py` |

---



### Authentication
| Feature | Status | Notes |
|---------|--------|-------|
| JWT Bearer auth | ✅ | `api/auth.py` — `POST /auth/login` returns token |
| Token expiry (24h) | ✅ | |
| Protected routes | ✅ | All `/memory/`, `/graph/`, `/episodic/` routes require Bearer |

### Endpoints
| Endpoint | Method | Status | Notes |
|----------|--------|--------|-------|
| `/health` | GET | ✅ | Unauthenticated |
| `/ready` | GET | ✅ | Unauthenticated |
| `/auth/login` | POST | ✅ | Returns JWT |
| `/memory/store` | POST | ✅ | |
| `/memory/retrieve` | POST | ✅ | Redis-cached |
| `/memory/search` | GET | ✅ | `?q=...` |
| `/graph/symbol/{name}` | GET | ✅ | Redis-cached |
| `/graph/callers/{function_name}` | GET | ✅ | |
| `/graph/subgraph/{entity}` | GET | ✅ | `?depth=2` |
| `/graph/stats` | GET | ✅ | |
| `/episodic/log` | POST | ✅ | |
| `/episodic/history` | GET | ✅ | `?limit=100` |
| `/episodic/search` | GET | ✅ | BM25 search |

### Redis Cache
| Feature | Status | Notes |
|---------|--------|-------|
| Optional Redis layer | ✅ | `api/cache.py` — graceful degradation when unavailable |
| `cache_get / cache_set` | ✅ | JSON serialized, configurable TTL |
| `cache_invalidate_prefix` | ✅ | Deletes `prefix:*` keys |
| `redis_status()` | ✅ | Returns `{connected, url, error}` |

---



| Feature | Status | Notes |
|---------|--------|-------|
| `QueryService.Query` (unary) | ✅ | Single request → response |
| `ContextService.StreamContext` (server-streaming) | ✅ | Streams context pack chunks |
| `QueryService.SubQueryStream` (client-streaming) | ✅ | Receives multiple sub-queries, aggregates |
| Proto files committed + CI freshness check | ✅ | `make proto` regenerates; CI diffs to detect stale |
| Idle timeout | ✅ | `--idle-timeout` flag |

---

## 10. Multi-Model Routing (Orchestrator)

**Files:** `orchestrator/classifier.py`, `orchestrator/router.py`

### Complexity Classifier
| Feature | Status | Notes |
|---------|--------|-------|
| Score-based tier assignment | ✅ | Heuristic scoring: tokens, entity count, vague referents, code markers |
| Tiers: QUICK / STANDARD / COMPLEX / EXPERT | ✅ | Score → tier boundary mapping |
| Config-driven model registry | ✅ | `config.json → models` section overrides defaults |
| Default routing: QUICK→local, STANDARD→Haiku, COMPLEX→Sonnet, EXPERT→Opus | ✅ | |
| Legacy tier migration | ✅ | `cognirepo migrate-config` renames v0.x tier keys to STANDARD/COMPLEX/EXPERT |

### Router
| Feature | Status | Notes |
|---------|--------|-------|
| Context bundle building | ✅ | `orchestrator/context_builder.py` |
| Local resolver (QUICK short-circuits) | ✅ | `local_adapter.py` + `try_local_resolve()` — zero-API |
| Provider fallback chain | ✅ | `_dispatch_with_fallback()` — anthropic → gemini → grok → openai |
| `_available_providers()` | ✅ | Checks env vars for API keys |
| Model adapters | ✅ | anthropic, gemini, grok, openai adapters in `orchestrator/model_adapters/` |
| Retry with exponential backoff | ✅ | `orchestrator/model_adapters/retry.py` |
| Error logging | ✅ | Date-stamped error logs in `.cognirepo/errors/` |
| Session history | ✅ | `orchestrator/session.py` — multi-turn conversation history |

---

## 11. IDE / AI Tool Integrations

| Integration | Status | File | Notes |
|-------------|--------|------|-------|
| Claude Desktop (MCP stdio) | ✅ | `interface/server/mcp_server.py` | Works with any MCP stdio client |
| Gemini CLI (`.gemini/COGNIREPO.md`) | ✅ | `.gemini/COGNIREPO.md` | Tool-first workflow instructions |
| Cursor (`.cursor/mcp.json`) | ✅ | `cli/init_project.py::_setup_cursor_mcp()` | Auto-generated by `cognirepo init` |
| VS Code (`.vscode/mcp.json`) | ✅ | `cli/init_project.py::_setup_vscode_mcp()` | `type: stdio` format |
| Claude (`.claude/CLAUDE.md`) | ✅ | `.claude/CLAUDE.md` | Tool-first workflow rules |
| OpenAI/Codex (REST + spec) | ✅ | `adapters/openai_spec.py` | Exports OpenAI-compatible function spec |
| Idempotent MCP config merge | ✅ | `setup_mcp()` | Re-runs merge without losing existing entries |

---

## 12. Init & Setup

| Feature | Status | Notes |
|---------|--------|-------|
| Interactive wizard | ✅ | `cli/wizard.py` — project name, encryption, multi-model, Redis, MCP targets |
| Scaffold `.cognirepo/` directories | ✅ | `_scaffold_dirs()` |
| Write `config.json` | ✅ | `_write_config()` |
| Write `.gitignore` (excludes `.cognirepo/`) | ✅ | `_write_gitignore()` |
| Idempotent re-run | ✅ | "Already initialized, updating..." |
| Auto-index prompt (Y/n) | ✅ | After scaffold |
| Auto-watcher prompt (Y/n) | ✅ | After index |
| Systemd prompt (y/N, Linux only) | ✅ | After watcher |
| "You're ready!" summary | ✅ | `_print_ready_summary()` — lists tools + token reduction estimate |
| `--non-interactive` flag | ✅ | No prompts; uses defaults for CI/scripting |
| `--no-index` flag | ✅ | Skip indexing entirely |
| Seed from git history | ✅ | `cli/seed.py::seed_from_git_log()` — populates behaviour graph |
| MCP config auto-setup | ✅ | `setup_mcp(targets, project_name, project_path)` |

---

## 13. Security

| Feature | Status | Notes |
|---------|--------|-------|
| AES-256 GCM encryption at rest | ✅ | `core/security/encryption.py`; key in OS keychain |
| OS keychain key storage | ✅ | `keyring` library |
| JWT authentication (REST) | ✅ | `api/auth.py` |
| Bcrypt password hashing | ✅ | Used for API password verification |
| MIT license headers | ✅ | All source files have SPDX headers |
| CI security gates | ✅ | Bandit (HIGH), TruffleHog (--only-verified), Trivy (CRITICAL/HIGH), pip-audit |
| Secret scanning in CI | ✅ | TruffleHog on full git history |

---

## 14. Documentation

| Document | Status | Location |
|----------|--------|---------|
| `README.md` | ✅ | Root |
| `ARCHITECTURE.md` | ✅ | Root + `docs/ARCHITECTURE.md` |
| `docs/MCP_TOOLS.md` | ✅ | All 34 MCP tools with signatures and examples |
| `docs/CLI_REFERENCE.md` | ✅ | All commands with flags |
| `docs/CONFIGURATION.md` | ✅ | config.json fields, env vars, storage layout |
| `docs/CONTRIBUTING.md` | ✅ | Dev setup, add-tool and add-language walkthroughs |
| `docs/SECURITY.md` | ✅ | Encryption, JWT, threat model |
| `CHANGELOG.md` | ✅ | Version history from v0.1.0 |
| `.claude/CLAUDE.md` | ✅ | Tool-first rules for Claude |
| `.gemini/COGNIREPO.md` | ✅ | Tool-first rules for Gemini CLI |

---

## 15. Test Coverage

89 test files under `tests/test_*.py` (run `venv/bin/python -m pytest tests/ --collect-only -q`
for the current test-function count). This table is representative, not exhaustive — see
`tests/` for the full list. The 89-file count is pinned against `tests/test_docs_sync.py`,
which fails if this number drifts from the real glob count.

| Test File | What it Covers |
|-----------|---------------|
| `test_memory.py` | FAISS store/retrieve, SemanticMemory |
| `test_graph.py` | KnowledgeGraph CRUD, traversal |
| `test_episodic_search.py` | BM25 ranking, cache lifecycle |
| `test_stale_cleanup.py` | Graph removal, watcher integration |
| `test_storage_adapter.py` | VectorStorageAdapter, FAISSAdapter, ChromaDB fallback |
| `test_cursor_vscode.py` | MCP config generation, idempotency |
| `test_proto_freshness.py` | .proto committed, pb2 importable |
| `test_api_cache.py` | Redis cache round-trip, graceful degradation |
| `test_doctor.py` | Doctor health checks, working-tree dirty warning |
| `test_ci_security.py` | CI security gate configuration |
| `test_ftx.py` | Init flow idempotency, non-interactive, ready summary |
| `test_docs_sync.py` | Classifier thresholds, edge type names, and this table's count match code |
| `test_classifier.py` | Tier classification heuristics |
| `test_hybrid_retrieval.py` | Signal merge, weights, cache |
| `test_context_builder.py` | Context bundle construction |
| `test_indexer_multilang.py` | Multi-language AST indexing |
| `test_behaviour_tracker.py` | Query tracking, interaction-style summarization, concurrent-save merge |
| `test_check_circular_deps.py` | Layer-invariant import-graph checker |

---

## 16. What is NOT Implemented (Honestly)

| Feature | Status | Notes |
|---------|--------|-------|
| ChromaDB backend (functional) | ⚠️ | Adapter exists but requires manual `pip install chromadb`; untested in CI |
| Vertex AI adapter | 🔲 | Not in codebase; REST API is the integration path |
| Web UI / dashboard | 🔲 | No web frontend; CLI + REST only |
| Automatic API key rotation | 🔲 | Keys loaded from env vars; no rotation logic |
| Multi-project shared memory | 🔲 | Each `.cognirepo/` is project-scoped; no cross-project retrieval |
| CogniRepo Cloud sync | 🔲 | All storage is strictly local |
| Fine-tuned embeddings | 🔲 | Uses `all-MiniLM-L6-v2` (general purpose); no project-specific fine-tuning |
| Plugin system | 🔲 | No plugin API; extend by forking |
| Automatic CALLS_API edge detection | ⚠️ | Auto-detected by `intelligence/indexer/http_call_scanner.py`, which scans outbound HTTP client calls (requests/httpx/aiohttp, fetch/axios, Go `net/http`) and matches URLs against registered sibling-service endpoints. Run `cognirepo org rewire` after indexing each child to build the edges; `cognirepo doctor` warns if children are registered but no CALLS_API edges exist yet. Manual declaration via `link_repos()` / `cognirepo org link-repos` still works as a fallback for calls the scanner's patterns miss. |
| Automatic SHARES_SCHEMA detection | 🔲 | Not implemented — must be declared manually via `link_repos()` MCP tool or `cognirepo org link-repos`. |

---

## 17. Microservices Setup Reference

Register a microservice and its relationships:

```bash
# Register child repo with metadata
cognirepo init --parent-repo /path/to/monorepo --service-type rest_api --port 8080 --api-base-url /api/v1

# CALLS_API is auto-detected — run after indexing each child:
cognirepo org rewire
# SHARES_SCHEMA has no scanner yet — declare manually:
# Via MCP tool:
link_repos(src="/path/to/api", dst="/path/to/auth", relationship="shares_schema")
# Via CLI:
cognirepo org link-repos /path/to/api /path/to/auth --type SHARES_SCHEMA
```

**Edge type auto-detection table:**

| Edge Type | Auto-detected? | How |
|-----------|---------------|-----|
| `IMPORTS` | ✅ Yes | Scans pyproject.toml, package.json, go.mod, Cargo.toml, requirements.txt |
| `CALLS_API` | ⚠️ Partial | `http_call_scanner.py` matches outbound HTTP calls to sibling endpoints via `cognirepo org rewire`; `link_repos()` remains a manual fallback for calls it misses |
| `SHARES_SCHEMA` | ❌ No | Must call `link_repos()` manually |
| `CHILD_OF` | ✅ Yes | Set via `cognirepo init --parent-repo` |
| `DISCOVERED` | ✅ Yes | Added by AI agents dynamically via `link_repos()` |
