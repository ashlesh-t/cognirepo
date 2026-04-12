# Changelog

All notable changes to CogniRepo are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
Versioning: [Semantic Versioning](https://semver.org/)

---

## [Unreleased]

### Added
- **Idle resource eviction** — `server/idle_manager.py` (`IdleManager`) evicts the SentenceTransformer embedding model, KnowledgeGraph, and ASTIndexer from RAM after a configurable idle TTL (default 10 min). Controlled via `idle_ttl_seconds` in `.cognirepo/config.json`. Resources reload lazily on next tool call with ~2 s warm-up. Frees ~400 MB+ for users who leave the MCP server running overnight.

### Fixed
- **Test suite cross-contamination** — eliminated all `sys.modules` pollution between test files. Root causes: unconditional `dotenv` stubbing clobbered real `python-dotenv` for `test_env_wizard.py`; `if dep not in sys.modules` stub guards installed MagicMocks when real packages existed but weren't cached yet; networkx DiGraph was mutated even on the real installed module; `rpc.proto.cognirepo_pb2_grpc` MagicMock caused `QueryServiceServicer` to be constructed as a Mock (inheriting from a Mock attribute loses all defined methods). Full suite: **850 passed, 15 skipped, 2 xfailed, 0 failures**.

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
- **Sprint 3.3** — `HealthServicer` on gRPC server (standard health proto). `client.health()` method with port-open fallback when `grpcio-health-checking` is not installed. `sub_query()` retries 3× with exponential backoff; `trace_id` propagated through gRPC metadata.
- **Sprint 3.3** — CI job `grpc-multiagent`: unit tests (health + retry), integration test with live gRPC server (health-poll gate before running tests).
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

- **Sprint 1** — AGPL-3.0 headers on all source files.
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
- Interactive REPL — `cognirepo chat`, readline history, special commands
- Local resolver — FAST-tier queries answered from local index with no model API call
- Multi-agent mode — DEEP queries delegate fast sub-lookups via gRPC (off by default)

**Transport layer**
- MCP stdio server — 8 tools for Claude Desktop, Gemini CLI, and other MCP clients
- FastAPI REST server — JWT auth, memory + episodic + graph routes, Swagger at /docs
- gRPC server — QueryService + ContextService for inter-model communication

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
- AGPL-3.0 license with SPDX headers on all source files
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
