# Changelog

All notable changes to CogniRepo are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
Versioning: [Semantic Versioning](https://semver.org/)

---

## [Unreleased]

---

## [1.0.0] — 2026-04-26

### Added

- **`cognirepo setup`** — one-command onboarding: init + index + writes MCP configs for Claude, Cursor, VS Code
- **`get_last_context()` MCP tool** — reads `~/.cognirepo/<repo>/last_context.json`; second agent resumes where first left off
- **`get_session_brief()` MCP tool** — returns architecture summary, hot symbols, entry points, index health; call at session start
- **`cognirepo ask` (local-only mode)** — zero-API query using QUICK-tier local resolver; no API keys required
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
- **`pyproject.toml`** — `fail_under` raised from 50 → 70; `Development Status` → `5 - Production/Stable`

### Fixed

- **`org_graph.py` concurrent writes** — added `_org_lock()` using `~/.cognirepo/org_graph.lock`; Fernet encrypt/decrypt on load/save
- **`config/lock.py`** — removed silent `_NoOpLock` fallback; now raises `ImportError` with actionable install hint
- **`episodic_bm25_filter` time_range** — BM25 now rebuilt from filtered events when `time_range` is active; was searching wrong event set
- **`to_undirected()` performance** — cached in `HybridRetriever.__init__`; was O(V+E) × 20 per query
- **Concurrent cache miss amplification** — `_IN_FLIGHT` dict + `threading.Event` dedup; N concurrent misses → 1 retrieve call

---

## [0.3.0] — 2026-04-24

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

## [Unreleased — prev sprint notes, to be sorted into next release]

### Added
- **AST FAISS in hybrid retrieval** (`retrieval/hybrid.py`) — `HybridRetriever._ast_faiss_retrieve()` queries the AST FAISS index (code symbols) directly via vector similarity. Previously `context_pack` and `retrieve_memory` returned empty results on freshly-indexed repos because `hybrid_retrieve` only queried the semantic memory FAISS (empty until memories are stored) and did exact-name entity lookup (which returns nothing for natural-language queries). All three paths now feed `_merge_candidates()` with vector_score promotion so FAISS scores upgrade exact-match candidates that had `vector_score=0.0`.
- **`repo_path` parameter on all MCP tools** (`server/mcp_server.py`) — `context_pack`, `lookup_symbol`, `who_calls`, `subgraph`, `graph_stats`, `search_token`, `semantic_search_code`, `retrieve_memory`, `store_memory`, `episodic_search`, `architecture_overview`, `dependency_graph`, `explain_change` now accept `repo_path: str | None = None`. When set, all reads/writes are scoped to that repo's storage directory using the thread-safe `_CTX_DIR` ContextVar, fresh graph/indexer instances are loaded (singletons untouched), and the correct source root is passed to `context_pack`'s file-window reader. Enables a single MCP server process to serve multiple indexed repos without cross-repo data leaks.
- **`_repo_ctx()` context manager** (`server/mcp_server.py`) — thread-safe scope switch for one tool call. Sets `_CTX_DIR`, loads fresh `KnowledgeGraph` + `ASTIndexer` for the target repo, and resets on exit. Module-level singletons are never mutated by cross-repo calls.
- **`repo_root` parameter on `context_pack()`** (`tools/context_pack.py`) — passed to `_read_window()` and `_file_mode_context()` so source file line-window extraction resolves paths relative to the target repo, not the server's working directory.
- **CI test workflow** (`.github/workflows/ci.yml`) — runs `pytest` on Python 3.11 and 3.12, bootstraps the project's own `.cognirepo` index before the suite, collects coverage, enforces `--cov-fail-under=50`. Fixes the broken `ci.yml` badge in README.
- **Idle resource eviction** — `server/idle_manager.py` (`IdleManager`) evicts the SentenceTransformer embedding model, KnowledgeGraph, and ASTIndexer from RAM after a configurable idle TTL (default 10 min). Controlled via `idle_ttl_seconds` in `.cognirepo/config.json`. Resources reload lazily on next tool call with ~2 s warm-up. Frees ~400 MB+ for users who leave the MCP server running overnight.

### Fixed
- **`lookup_symbol(include_org=True)` thread-safety** (`server/mcp_server.py`) — replaced `set_cognirepo_dir(original_dir)` / `get_cognirepo_dir()` process-wide globals (racy under concurrent MCP calls) with `_CTX_DIR.set()` / `_CTX_DIR.reset()` ContextVar pattern already used by `CrossRepoRouter`.
- **`_who_calls_dynamic_fallback` repo root** (`server/mcp_server.py`) — grep fallback for dynamic dispatch now receives explicit `repo_root` from `_repo_ctx`, so it searches the correct directory when `repo_path` is specified.
- **Test suite cross-contamination** — eliminated all `sys.modules` pollution between test files. Root causes: unconditional `dotenv` stubbing clobbered real `python-dotenv` for `test_env_wizard.py`; `if dep not in sys.modules` stub guards installed MagicMocks when real packages existed but weren't cached yet; networkx DiGraph was mutated even on the real installed module; `rpc.proto.cognirepo_pb2_grpc` MagicMock caused `QueryServiceServicer` to be constructed as a Mock (inheriting from a Mock attribute loses all defined methods). Full suite: **702 passed, 14 skipped, 2 xfailed, 0 failures**.

---

## [1.0.0] — 2026-04-10

### Added

- **Sprint 4.1** — `pytest-cov` in dev extras; CI runs with `--cov` and uploads HTML artifact; coverage fail-under gate at 50% baseline.
- **Sprint 4.1** — `GET /status/detailed` REST endpoint returns full diagnostics JSON (uptime, FAISS size, graph stats, circuit breaker, multi-agent flag) — no auth required.
- **Sprint 4.1** — `deploy/grafana/cognirepo.json` — pre-built Grafana 10 dashboard wired to Prometheus metrics (HTTP rate, latency p50/p95, FAISS vectors, graph nodes/edges, circuit breaker gauge, retrieval latency, memory op rate).
- **Sprint 4.2** — `scripts/release_checklist.md` — manual pre-release checklist (version bump, CHANGELOG, RC dry-run, OIDC setup, stable tag).
- **Sprint 4.2** — `scripts/check_wheel.sh` extended with Step 5: Tier-1 REPL Q&A via stdin after installing `[cli]` extras.
- **Sprint 4.3** — `docs/CLI.md` — full interactive REPL reference (slash commands, tiers, session persistence, multi-agent mode, environment variables, CLI config).

### Changed

- **Sprint 4.2** — `publish.yml` migrated to OIDC trusted publishing (no long-lived `PYPI_API_TOKEN`); added `publish-testpypi` job for rc/alpha/beta tags; added `wheel-smoke` job between build and publish.
- **Sprint 4.3** — Docs sweep: all tier names updated to QUICK/STANDARD/COMPLEX/EXPERT in `ARCHITECTURE.md`, `USAGE.md`, `FEATURE.md`.

### Breaking

- **Sprint 3.1** (v0.5.0) — Tier names renamed: `FAST→STANDARD`, `BALANCED→COMPLEX`, `DEEP→EXPERT`. `config.json` using old names raises `ConfigMigrationError`. Auto-fix: `cognirepo migrate-config`.

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

[Unreleased]: https://github.com/ashlesh-t/cognirepo/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ashlesh-t/cognirepo/releases/tag/v0.1.0
