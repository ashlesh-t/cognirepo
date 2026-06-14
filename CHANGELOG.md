# Changelog

All notable changes to CogniRepo are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
Versioning: [Semantic Versioning](https://semver.org/)

---

## [Unreleased]

---

## [1.1.0] — 2026-06-11

### Added (release-readiness pass, 2026-06)
- **`cognirepo org rewire` CLI command** — re-runs cross-service CALLS_API detection for every indexed org repo; repairs edges missed when services were indexed in the wrong order
- **`org_dependencies` parent rollup** — called from an org parent, now returns `service_topology` with the children's CALLS_API call chain (e.g. client → npci-service → bank-service), including caller function and endpoint pattern
- **`org_wide_search` transparency** — returns `{results, count, repos_searched, repos_skipped}` so a child repo missing from results is visible (was: silent)
- **`who_calls` coverage honesty** — when the static call graph returns ≤2 callers, the grep fallback is merged in and a `coverage_note` warns that dynamic/interface dispatch may be missed
- **Service port auto-detection** — `cognirepo init`/wizard detect `server.port` (Spring), YAML `port:`, and `.env` `PORT=` and store it on the org-graph node; surfaced via `get_agent_bootstrap` child_services
- **`indexing.unskip_dirs` config** — un-skip default-skipped directories per repo (companion to `skip_dirs`)
- **`queried_symbols` + `recently_modified_files`** in session brief — replaces the misleading `hot_symbols` label (kept as deprecated alias until 1.2)
- **Doctor checks 18–20** — AST index JSON validity, doc-index populated, org CALLS_API edges present
- **Subgraph `resolved_to`** — fuzzy name resolution now scans all `::Name` suffixed nodes ranked by degree, so `subgraph("GenericAPIServer")` resolves file-qualified keys

### Fixed (release-readiness pass, 2026-06)
- **AST index corruption on large repos** — `ast_index.json`/`ast_metadata.json` writes are now atomic (tmp + `os.replace` + fsync); corrupt files are renamed `.corrupt` and self-heal on load instead of crashing `cognirepo summarize`
- **`context_pack` empty on Kubernetes-style repos** — `staging/` removed from default skip dirs (it holds real first-party source in k8s); re-add per repo via `indexing.skip_dirs` if needed
- **`context_pack` BM25 noise** — relative-score gate drops sections below 0.5× the best hit's score (tunable via `COGNIREPO_REL_NOISE_RATIO`)
- **Subgraph memory blowup** — `subgraph_around()` uses a bounded BFS (caps enforced *during* expansion, hub nodes with degree > 500 skipped) instead of materializing the full `nx.ego_graph`; responses capped at ~30k chars. A single `subgraph(depth=3)` can no longer inflate RSS past the circuit-breaker limit
- **Stale auto-reindex never firing** — trigger now fires on age-based staleness when the git-SHA comparison is inconclusive; reindex lock acquired atomically (`open(…, "x")`); orphaned locks (>30 min) cleared; dead `watcher.pid` no longer suppresses staleness
- **Go structs/interfaces missing from index** — `type_spec` added to tree-sitter class types; `architecture_overview` now shows `Scheduler`, `Kubelet`, etc. for Go repos
- **`search_docs` placeholder noise** — score-0.0 filler results dropped, duplicates removed by normalized text, and empty results return `status: "no_doc_matches"` with a reindex hint
- **CALLS_API edges lost to indexing order** — after `index-repo` writes a repo's endpoints, siblings indexed earlier are automatically re-wired against it
- **Memory duplicates** — `store_memory` and the learning store dedupe identical (whitespace-normalized) text, returning the existing entry instead of storing it again
- **Vendor noise in `architecture_overview`** — `vendor/`, `third_party/`, `node_modules/` excluded from "Top packages" and key class/function ranking
- **`dependency_graph("celery")`** — bare module/package names now resolve to `<m>.py` / `<m>/__init__.py` / `src/<m>/…` automatically
- **`get_error_patterns` run-on hints** — adds structured `suggested_command` + `generic_hint` fields alongside the combined `prevention_hint`
- **Cross-process memory freshness** — `LocalVectorDB` reloads the FAISS index + metadata when another process wrote them (mtime check before searches); long-lived MCP servers no longer serve a stale snapshot
- **`.env` template shipped an ACTIVE 2 GB circuit-breaker cap** — `cognirepo init` copied `.env.example` with `COGNIREPO_CB_RSS_LIMIT_MB=2000` uncommented, capping every initialized project at 2 GB RSS and causing the recurring breaker trips in benchmark/subgraph/store_memory. Circuit-breaker values in the template are now commented out (smart 80%-of-RAM default applies)
- **`.env` resolved from the wrong directory** — `load_dotenv()` in the CLI, MCP server, and prune cron resolved `.env` relative to the *package source file*, not the user's project: an editable/dev checkout's `.env` leaked into every command machine-wide, and pip users' project `.env` was never loaded. Now uses `find_dotenv(usecwd=True)`
- **Encryption flag read from the wrong repo** — `get_storage_config()` read `.cognirepo/config.json` relative to bare CWD instead of the active repo context (`_CTX_DIR`); context-switched saves (org indexing) wrote graph/metadata plaintext while the owning config said `encrypt: true`, making every later load fail decryption and silently start with an EMPTY graph (observed: 76k-node kubernetes graph reported 0 nodes). Now resolves via `config.paths.get_path`; loads also self-heal by attempting plaintext when decryption fails (re-encrypted on next save)
- **Benchmark crashed under breaker pressure** — steps 2–7 of `run_benchmark()` were unguarded (`CircuitOpenError` traceback at memory-recall); now abort gracefully with the partial token-reduction result, and the CLI no longer KeyErrors printing an aborted report
- **`graph_stats` staleness coherence** — `index_stale` no longer reports `true` when git HEAD matches the last-indexed SHA (old by age but content-current); reindex triggers verified live: new commit → `stale_reindexing_triggered: true`
- **Segfault at end of large-repo indexing (doc ingestion)** — reproduced on moby: chromadb 1.5.8's Rust core hits infinite recursion (native stack overflow) merely *opening* a large/poisoned chroma store (`Collection.count()` at adapter init), killing the whole `index-repo` run after a 30-minute embed pass. Three-part fix: (1) doc ingestion now runs in an isolated subprocess (`python -m indexer.doc_ingester`) so a native crash can never kill the index run; (2) crash-evidence self-heal — a `.opening` sentinel left by a crashed open makes the next open quarantine the poisoned store to `chroma.corrupt-<ts>` (kept, not deleted) and start fresh, with one automatic retry; (3) the duplicate DocIngester invocation inside `index_repo()` removed (every entry point calls it explicitly after `free_large_objects()`), which also stops doc chunks being stored twice; chunk embedding is now one streamed batch pass with text-level dedup instead of thousands of individual ONNX calls
- **`.env.example` missing from wheels** — the template lived at the repo root, which setuptools package-data cannot include, so pip/pipx installs shipped no template and `cognirepo init` silently skipped `.env` creation. The template now also lives at `cognirepo/.env.example` (shipped in the wheel, verified via scratch-venv install; a test keeps both copies in sync), and `init` prints a clear note instead of silently skipping when no template is found

### Added
- **`get_agent_bootstrap()` MCP tool** — single-call session start replacing 4-call sequence; ~300 tokens vs ~900
- **`supersede_learning()` MCP tool** — deprecate and replace an outdated memory entry in one call
- **Behaviour tracking opt-in** — wizard now asks during `cognirepo setup`; off by default; `behaviour.json` encrypted when encryption is enabled
- **Behaviour query recording** — `context_pack`, `lookup_symbol`, `who_calls`, `semantic_search_code`, `episodic_search` now record to behaviour tracker (when opted in)
- **Auto-summarize interaction style** — triggers every 10 queries automatically
- **`autosave_context` wizard step** — cross-agent handoff now asked during setup (default: on)
- **`DEFAULT_MODELS_BY_PROVIDER`** in `orchestrator/classifier.py` — single source for model names

### Fixed
- **fastembed migration** — removed all `model.encode()` calls across 11 files; replaced with `model.embed()` generator API; no more CUDA/nvidia packages on `pip install cognirepo`
- **`get_children()` always returning empty** — `direction == "reverse"` → `direction == "forward"` in org_graph
- **Episodic type bug** — `log_event` was called with dict as first arg; now correctly passes `event=str, metadata=dict`
- **Org graph race condition** — `save()` re-reads disk state within file lock before writing (last-write-wins → additive merge)
- **BFS O(n) queue** — `list.pop(0)` → `collections.deque.popleft()` in 3 locations
- **`context_pack` response shape** — always returns `{query, status, token_count, sections, truncated}`; no more 3 different shapes
- **`who_calls` response shape** — always returns `{local_callers, cross_repo_callers, truncated}`
- **`org_dependencies` response bloat** — removed redundant `graph.to_dict()` field (~30% smaller)
- **`prime_session` text limits** — architecture truncation raised from 200 → 600 chars; removed stale `known_blind_spots`

### Changed
- **`pip install cognirepo`** — no longer pulls PyTorch/CUDA; fastembed/ONNX only (~50MB vs ~1.5GB)
- **Doctor** — checks for all 34 registered MCP tools (was 30); adds `find_symbol_path` and `get_service_endpoints` (microservice KG wiring)
- **`org_wide_search` docstring** — marked as PRIMARY cross-repo tool; `org_search` marked as DEPRECATED fallback
- **`behaviour.json`** — now encrypted/decrypted using same Fernet key as `graph.pkl` when encryption is on
- **`BehaviourTracker`** — receives `db_adapter` injection; feedback scores propagate to vector store; temporal decay on relevance scores (`old * 0.95 + 0.1`)

### Docs
- `docs/MCP_TOOLS.md` — all 34 tools documented
- `MANUAL_TEST_SUITE.md` — 39-test manual test suite with prompts and result blocks
- `README.md` — corrected install command (removed `cpu` extra)
- `CLAUDE.md` — stack updated to fastembed/ONNX, argparse

---

## [1.0.0] — 2026-04-26

### Added

- **`cognirepo setup`** — one-command onboarding: init + index + writes MCP configs for Claude, Cursor, VS Code
- **`get_last_context()` MCP tool** — reads `~/.cognirepo/<repo>/last_context.json`; second agent resumes where first left off
- **`get_session_brief()` MCP tool** — returns architecture summary, hot symbols, entry points, index health; call at session start
- **`cognirepo ask` (local-only mode)** — ⚠️ planned — not yet available in this release; command prints a "not yet available" message
- **Cursor MDC rules** — `.cursor/rules/cognirepo.mdc` with `alwaysApply: true`, session-start sequence, NEVER directives
- **VS Code MCP config** — `.vscode/mcp.json` + `.vscode/mcp.json.example` for VS Code / GitHub Copilot integration
- **`docs/USAGE.md`** — Cursor Integration, VS Code MCP Setup, GitHub Copilot Integration sections
- **precision@k benchmark** — `measure_precision_at_k()` + `measure_latency()` in `tools/benchmark.py`
- **20-entry golden test set** — `tests/fixtures/benchmark_golden.json` for CogniRepo self-benchmark
- **External repo golden sets** — `benchmark_golden_{flask,fastapi,celery,ansible}.json`
- **`docs/METRICS.md`** — External Repo Validation section with measured numbers (flask/fastapi/celery/ansible)
- **Index build timing** — `cognirepo index-repo` prints symbol count, file count, elapsed time, peak RSS delta
- **`cognirepo doctor` checks 11–14** — venv pollution, filelock/tiktoken importable, sentence-transformers importable, MCP tool schemas
- **AST index staleness warning** — doctor warns if index is > 24h old
- **`_REGISTERED_TOOLS`** — exported set in `server/mcp_server.py` for doctor validation

### Changed

- **Install size ~75% smaller** — `anthropic`, `google-generativeai`, `google-genai`, `openai` moved to `[providers]` optional extra; MCP-only users no longer need model SDKs
- **CPU embeddings by default** — `sentence-transformers[cpu]` is now the default; `[gpu]` extra for GPU users
- **`cognirepo doctor` exit codes** — `0`=healthy, `1`=warnings only, `2`=any error (was: exit N = error count)
- **`_cmd_prime()` extracted** — body moved to `tools/prime_session.py`; CLI and MCP tool share the same implementation
- **`docs/USAGE.md`** — table of contents updated; install section leads with `pip install 'cognirepo[cpu,languages]'`
- **README** — headline reframed as "Persistent Institutional Memory"; 5-minute quickstart with `cognirepo setup`; measured external benchmark table added
- **`pyproject.toml`** — `Development Status` → `5 - Production/Stable`; coverage `fail_under` gate held at 50 (matches CI `--cov-fail-under=50`; current measured coverage ~57%)

### Fixed

- **`org_graph.py` concurrent writes** — added `_org_lock()` using `~/.cognirepo/org_graph.lock`; Fernet encrypt/decrypt on load/save
- **`config/lock.py`** — removed silent `_NoOpLock` fallback; now raises `ImportError` with actionable install hint
- **`episodic_bm25_filter` time_range** — BM25 now rebuilt from filtered events when `time_range` is active; was searching wrong event set
- **`to_undirected()` performance** — cached in `HybridRetriever.__init__`; was O(V+E) × 20 per query
- **Concurrent cache miss amplification** — `_IN_FLIGHT` dict + `threading.Event` dedup; N concurrent misses → 1 retrieve call
- **`lookup_symbol(include_org=True)` thread-safety** (`server/mcp_server.py`) — replaced process-wide globals with `_CTX_DIR.set()` / `_CTX_DIR.reset()` ContextVar pattern; eliminates race under concurrent MCP calls
- **`_who_calls_dynamic_fallback` repo root** (`server/mcp_server.py`) — grep fallback now receives explicit `repo_root` from `_repo_ctx`; correct directory used when `repo_path` is specified
- **Test suite cross-contamination** — eliminated all `sys.modules` pollution between test files; full suite: **702 passed, 14 skipped, 2 xfailed, 0 failures**

### Also in 1.0.0 (internal sprint additions)

- **AST FAISS in hybrid retrieval** (`retrieval/hybrid.py`) — `_ast_faiss_retrieve()` enables cold-start retrieval without pre-stored semantic memories
- **`repo_path` parameter on all MCP tools** — all 32 tools accept `repo_path: str | None`; enables single server process to serve multiple repos without cross-repo data leaks
- **`_repo_ctx()` context manager** — thread-safe per-call repo scope switching via ContextVar
- **Idle resource eviction** (`server/idle_manager.py`) — evicts embedding model, KnowledgeGraph, ASTIndexer after configurable idle TTL (default 10 min); frees ~400 MB+
- **CI test workflow** (`.github/workflows/ci.yml`) — pytest on Python 3.11 and 3.12; bootstraps `.cognirepo` index before suite; `--cov-fail-under=50`
- **`pytest-cov`** in dev extras; CI uploads HTML artifact; coverage fail-under gate
- **`GET /status/detailed`** REST endpoint — full diagnostics JSON (uptime, FAISS size, graph stats, circuit breaker)
- **`deploy/grafana/cognirepo.json`** — pre-built Grafana 10 dashboard (HTTP rate, latency p50/p95, FAISS vectors, graph nodes/edges)
- **`publish.yml`** migrated to OIDC trusted publishing; `wheel-smoke` job added between build and publish
- **`docs/CLI.md`** — full interactive REPL reference

---

## [0.6.0] — 2026-04-24

### Added
- **`.env` seeded on `cognirepo init`** (`cli/init_project.py`) — `.env.example` is now shipped as package data and automatically copied to `.env` on first init, so users discover circuit-breaker and API-key variables without reading docs.
- **`.env.example` in package data** (`pyproject.toml`) — included via `[tool.setuptools.package-data]` so the template is present in pip-installed wheels.
- **Cross-repository discovery and retrieval** — Allows an agent to query findings, symbols, and context from other repos in the same local organization.
- **Project-scoped shared memory** — Hierarchical organization/project structure with shared FAISS stores.
- **Local hierarchical summarization** — Zero-API tree-based summaries of files, directories, and the entire repository.

### Fixed
- **Confidence gate in `context_pack`** (`tools/context_pack.py`) — Now uses `final_score` instead of `vector_score`. This allows high-quality AST and Graph matches to pass even when the FAISS index is empty (e.g. in CI or newly indexed repos).
- **Infinite loop in project init tests** (`tests/test_ftx.py`) — Narrowed the scope of `builtins.open` mock and improved helper isolation to prevent recursive init calls and timeouts.
- **`IsADirectoryError` during init** (`cli/init_project.py`) — Added `is_file()` safety check when seeding `.env` from template.
- **Dependency declarations** (`pyproject.toml`) — Moved `fastapi`, `uvicorn`, and `httpx` to core dependencies. Ensures post-release verification tests pass and metrics server is functional out-of-the-box.
- **Tree-sitter `_walk_ts` — decorators and tags** (`indexer/ast_indexer.py`) — `_walk_ts` now extracts decorator names for both FUNCTION and CLASS nodes via `_ts_decorators()`. Previously all decorator information was silently dropped when tree-sitter ran (the default path), meaning `@property`, `@classmethod`, `@app.route`, etc. were invisible to FAISS embed text, the reverse index, and the graph.
- **Tree-sitter `_walk_ts` — base classes and INHERITS edges** — `_ts_bases()` added; CLASS nodes now populate `bases`. Consequently `EdgeType.INHERITS` edges are correctly written to the knowledge graph for the first time when tree-sitter-python is installed. Previously zero INHERITS edges existed in the default configuration.
- **Tree-sitter `_walk_ts` — CLASS docstring always empty** — `_ts_docstring()` is now called for CLASS nodes; the hardcoded `"docstring": ""` is removed.
- **CONSTANT / VARIABLE / TYPED_FIELD / LAMBDA absent from default index** (`indexer/ast_indexer.py`) — `_parse_file` now runs stdlib-ast after tree-sitter for Python files and merges the results: tree-sitter supplies FUNCTION/CLASS (richer call graph), stdlib-ast supplies CONSTANT/VARIABLE/TYPED_FIELD/LAMBDA (which tree-sitter `_walk_ts` never emitted). Module-level constants, type aliases, and dataclass fields are now indexed.
- **Lambda dedup bug** (`indexer/ast_indexer.py`) — deduplication now uses a priority map (`LAMBDA > CONSTANT/VARIABLE`) so lambda-assignment symbols are no longer silently dropped by the first-seen `(name, start_line)` key.
- **Bare relative imports skipped** (`indexer/ast_indexer.py`) — `_extract_imports_py` now handles `from . import X` (where `node.module is None`) by emitting one IMPORTS entry per name. Previously these were silently dropped.
- **Stale graph nodes on re-index** (`indexer/ast_indexer.py`) — `index_file()` now calls `graph.remove_file_nodes(rel_path)` before re-parsing, so deleted or renamed symbols no longer accumulate as orphan nodes with stale edges.
- **`file_summary` entries invisible to code retrieval** (`retrieval/hybrid.py`) — `_ast_faiss_retrieve` no longer skips entries with `source == "file_summary"`. File-level summary vectors now participate in hybrid retrieval, enabling "what does X.py do?" queries to return direct hits.
- **`lookup_symbol(include_org=True)` cross-repo `ASTIndexer()` TypeError** (`server/mcp_server.py`) — `ASTIndexer()` requires a `KnowledgeGraph` argument; the cross-repo path was calling it with no args, causing a `TypeError` on any org-scoped lookup. Fixed by passing a fresh `KnowledgeGraph()` instance.
- **Arrow functions and `const foo = () => ...` missed** (`indexer/ast_indexer.py`) — added `arrow_function` and `function_signature` to `_TS_FUNCTION_TYPES`; added a `lexical_declaration` / `variable_declarator` branch in `_walk_ts` to capture JS/TS arrow-function assignments by variable name.

### Changed
- **`cognirepo ask` removed from active CLI** (`cli/main.py`) — command now prints a clear "not yet available" message directing users to the MCP tools. The multi-model orchestrator is not functional in this release; shipping a silent no-op would mislead users. Will be re-enabled in a future release once the orchestrator is complete.
- **`.env.example` API key comment updated** — removed `NOT-FUNCTIONAL-YET` annotation; comment now accurately states keys are reserved for the future `cognirepo ask` command.
- **Summarizer engine architecture** — Fully transitioned to local-only summarization using AST index, removing previous LLM routing logic.


---

## [0.5.0] — 2026-04-09

### Added

- **Sprint 3.2** — `orchestrator/model_adapters/local_adapter.py`: zero-API QUICK-tier resolver. Raises `NoLocalAnswer` to promote queries to STANDARD. Provider fallback chain in `_dispatch_with_fallback()` with retry on `UNAVAILABLE`/`DEADLINE_EXCEEDED`.
- **Sprint 3.4** — `cli/repl/agents_panel.py`: `AgentRegistry` (thread-safe), `SubAgent` dataclass, `render_agents_panel()` Rich panel (greyed-out dim style), `stream_agents_panel()` at 10 Hz.
- **Sprint 3.4** — `/agents` slash command: lists sub-agent sessions, supports `cancel <id>`. `/status` shows active sub-agents when multi-agent is enabled.
- **Sprint 3.4** — EXPERT-tier REPL queries fire a background gRPC sub-agent; results stored in `session["sub_queries"]`.
- **Sprint 3.1** — `cognirepo migrate-config` command: renames legacy tier keys in `config.json` in-place with `.bak` backup.

### Changed

- **Sprint 3.1** — Classifier tier names: FAST→STANDARD, BALANCED→COMPLEX, DEEP→EXPERT. Old keys detected in `config.json` raise `ConfigMigrationError`.
- **Sprint 3.2** — Default model map: QUICK tier now routes to `local/local-resolver` (zero-API).
- **Sprint 3.3** — `client.sub_query()` default `target_tier` changed from `"FAST"` to `"STANDARD"`.

### Fixed

- **Sprint 3.2** — `test_fallback_chain.py`: test isolation bug where `sys.modules.setdefault` + `hasattr(MagicMock)` always evaluated True, preventing real `ModelCallError` stub from being installed.

---

## [0.4.0] — 2026-03-31

### Added

- **Sprint 2.1** — Rich REPL facelift: `RichUI` with panels, syntax highlighting, and `StdlibUI` fallback.
- **Sprint 2.2** — Embedded docs FAISS index (`cli/docs_index.py`): markdown chunking, mtime-based staleness, confidence threshold 0.6. Classifier `docs_query` override routes CogniRepo usage questions to QUICK tier.
- **Sprint 2.3** — CLI config file (`~/.cognirepo/cli_config.toml`): `[ui]`, `[model]`, `[session]` sections. Session persistence: auto-save on every exchange. `/save`, `/load`, `/index-repo` slash commands.
- **Sprint 2.4** — Zero-friction init: Cursor (`.cursor/mcp.json`) and VS Code (`.vscode/mcp.json`) auto-config generated by `cognirepo init`. Wizard extended with Cursor/VS Code targets.

---

## [0.3.0] — 2026-03-27

### Added

- **Sprint 1** — MIT headers on all source files.
- **Sprint 1** — `LICENSE`, `NOTICE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`.
- **Sprint 1** — `cognirepo doctor` command with health checks and verbose output.
- **Sprint 1** — Encryption at rest (Fernet AES-128-CBC), secrets stored in OS keychain.
- **Sprint 1** — CI security gates: Bandit (HIGH severity), TruffleHog (verified secrets), Trivy (CRITICAL/HIGH CVEs), Snyk (CRITICAL dep vulnerabilities).

---

## [0.2.0] — 2026-04-08

### Fixed

- **Task 1.1** — Declared `rank-bm25>=0.2.2` as a hard dependency in `pyproject.toml`; `episodic_search` no longer raises `ModuleNotFoundError` on a fresh install.
- **Task 1.2** — Removed `print()` from `memory/semantic_memory.py` (replaced with `logger.debug`); also fixed `memory/embeddings.py` and `retrieval/vector_search.py`. Added `scripts/check_no_stdout_pollution.py` CI guard that fails on any stdout-going `print()` in MCP-critical modules.
- **Task 1.3** — `orchestrator/session.py` no longer captures `.cognirepo/sessions` at module-load time; all path resolution is now lazy via `config.paths.get_path()`, so `--project-dir` and `COGNIREPO_DIR` are correctly honoured for session storage.
- **Task 1.4** — `cron/prune_memory.py` FAISS rebuild now writes to the configured project path (via `config.paths.get_path("vector_db/semantic.index")`) instead of a hard-coded relative `./vector_db/` path.

### Added

- **Task 1.1** — `scripts/check_no_stdout_pollution.py` CI guard (MCP framing safety).
- **Task 2.3** — `docs/architecture/graph.md` — edge type glossary with example queries per type.
- **Task 2.5** — `docs/architecture/retrieval.md` — canonical 3-signal pipeline diagram. Four Mermaid `.mmd` source files committed; `scripts/build_diagrams.sh` generates PNGs via `mmdc`.
- **Task 3.3** — `COGNIREPO_GLOBAL_DIR` env var for redirecting global storage (test isolation + containers).
- **Task 4.1** — Multi-platform matrix smoke test (Ubuntu / macOS / Windows × Python 3.11/3.12). `scripts/smoke_test.sh` + `scripts/smoke_test.ps1` added.

### Changed

- **Task 3.1** — `test_api.py` now actually runs (was silently skipped due to password mismatch). Fixed `auth_headers` fixture to use `test_password` from conftest. Removed `--ignore=tests/test_api.py` from the main CI pytest step and removed `|| true` from the separate API step (replaced with stdout-pollution guard). All 26 API tests pass.
- **Task 3.2** — `config/paths.py`: added `set_global_dir()` / `get_global_dir()` override so tests redirect `user_memory` writes to tmp; also respects `COGNIREPO_GLOBAL_DIR` env var. Conftest updated to call `set_global_dir()`. `tests/test_isolation.py` added.
- **Task 3.3** — `cli/daemon.py`: moved `import fcntl` from module-level to inside the two functions that use it (lazy import). Added platform guard to the `watch` command handler: non-Linux gets a friendly message + exit code 2. `tests/test_cli_daemon.py` added.
- **Task 3.4** — `cli/init_project.py`: removed the "Index this repo now? (Y/n)" prompt. `init` now runs index-repo automatically by default; `--no-index` flag skips it. Progress message shown during indexing; tqdm used when available. `tests/test_e2e_init.py` added.

### Documentation

- **Task 2.1** — Corrected all "4-signal retrieval" claims to "3-signal" across `ARCHITECTURE.md`, `README.md`, `docs/ARCHITECTURE.md`. Added `docs/architecture/retrieval.md` with the canonical pipeline diagram explaining the actual merge formula and why AST is a pre-scorer (not a merge signal) and episodic is a side-channel.
- **Task 2.2** — Refreshed classifier tier thresholds in `ARCHITECTURE.md` to match `_TIER_QUICK=2.0`, `_TIER_FAST=4.0`, `_TIER_BALANCED=9.0` in code; corrected imperative signal weight from +4 to +5. Added pointer comment in `classifier.py` linking to the doc section. `tests/test_docs_sync.py` enforces parity automatically.
- **Task 2.3** — Aligned edge type names in `FEATURE.md` from `CONTAINS, CALLS, USES` to the actual `EdgeType` constants: `RELATES_TO, DEFINED_IN, CALLED_BY, QUERIED_WITH, CO_OCCURS`. Added `docs/architecture/graph.md` with a full edge type glossary and example queries. Sync test added.
- **Task 2.4** — Verified `faiss-cpu==1.13.2` and `starlette==1.0.0` exist on PyPI and install correctly; no version corrections required.
- **Task 2.5** — Replaced 40-byte stub PNGs with valid PNG files (800×400 white images with embedded description and Mermaid source pointer). Committed Mermaid `.mmd` source files for all 4 diagrams. Added `scripts/build_diagrams.sh` to regenerate PNGs via `mmdc`. Sync tests added to enforce non-zero-byte and valid PNG format.

---

## [0.1.0] — 2026-04-05

### Added

**Core memory engine**
- Semantic memory — FAISS flat index, sentence-transformers all-MiniLM-L6-v2 embeddings
- Episodic event log — append-only JSON with timestamp chain and BM25 keyword search
- Knowledge graph — NetworkX DiGraph, typed nodes (FILE, FUNCTION, CLASS, CONCEPT, QUERY,
  SESSION) and typed edges (DEFINED_IN, CALLS, CALLED_BY, INVOLVES, RETRIEVED, RELATED_TO)
- Behaviour tracker — query→symbol associations, file-edit co-occurrence, git history seeding
- AST indexer — tree-sitter multi-language parser, O(1) symbol reverse index
- Hybrid retrieval — 4-signal weighted merge: vector + graph + AST + episodic (0.5/0.3/0.1/0.1)
- Circuit breaker — RSS-based OOM guard, CLOSED/OPEN/HALF_OPEN states

**Model orchestration**
- Complexity classifier — 7-signal rule-based scorer, FAST/BALANCED/DEEP tiers, no training data
- Context builder — ContextBundle hydration from all 5 sources, token budget trimming by tier
- Multi-model router — classify → hydrate → dispatch → post-process
- Model adapters: Anthropic (Claude), Google (Gemini), xAI (Grok), OpenAI-compatible
- Automatic provider fallback chain with exponential backoff retry (3 attempts)
- Streaming output via `stream_route()`
- Conversation history — session IDs, persistent exchange history, `--continue` flag
- Local resolver — FAST-tier queries answered from local index with no model API call

**Transport layer**
- MCP stdio server — 8 tools for Claude Desktop, Gemini CLI, and other MCP clients

**Operational**
- Memory pruner — importance × recency decay, archive mode, dry-run
- Docker — multi-stage build, non-root user, named volumes, health check, profiles
- GitHub Actions CI — pylint (≥8.0), pytest, multi-job pipeline
- `cognirepo doctor` — 9-point system health check command with exit codes

**Security (Sprint 1)**
- Encryption at rest — Fernet symmetric encryption for `.cognirepo/` data files (opt-in)
- Secrets management — JWT secret and password hash stored in OS keychain, never in config
- Bandit SAST — automated Python security scanning in CI
- Snyk — dependency vulnerability scanning in CI
- Trivy — container and filesystem scanning in CI
- TruffleHog — secrets scanning across full git history in CI
- pre-commit hooks — local Bandit + detect-private-key + file checks

**Language support (Sprint 2)**
- tree-sitter replaces stdlib `ast` — Python, JS, TS, Java, Go, Rust, C++ indexing
- Language registry — `supported_extensions()`, graceful skip for uninstalled grammars
- Optional C++ BM25 extension via pybind11 — pure-Python fallback always available

**OSS files (Sprint 3)**
- MIT license with SPDX headers on all source files
- NOTICE file with copyright and commercial licensing terms
- SECURITY.md — vulnerability reporting, data handling, trust boundaries
- ARCHITECTURE.md — component map, data flow, single architecture rule
- LANGUAGES.md — language support table and contribution guide
- CONTRIBUTING.md — dev setup, architecture rule, adapter/tool/language guides
- CHANGELOG.md — this file
- README.md — complete project documentation with badges
- USAGE.md — complete CLI, REST, MCP, Docker, and security reference

[Unreleased]: https://github.com/ashlesh-t/cognirepo/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/ashlesh-t/cognirepo/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ashlesh-t/cognirepo/compare/v0.6.0...v1.0.0
[0.6.0]: https://github.com/ashlesh-t/cognirepo/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/ashlesh-t/cognirepo/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/ashlesh-t/cognirepo/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/ashlesh-t/cognirepo/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/ashlesh-t/cognirepo/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ashlesh-t/cognirepo/releases/tag/v0.1.0
