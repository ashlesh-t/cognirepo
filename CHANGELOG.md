# Changelog

All notable changes to CogniRepo are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
Versioning: [Semantic Versioning](https://semver.org/)

---

## [Unreleased]

### Fixed

- **Task 1.1** — Declared `rank-bm25>=0.2.2` as a hard dependency in `pyproject.toml`; `episodic_search` no longer raises `ModuleNotFoundError` on a fresh install.
- **Task 1.2** — Removed `print()` from `memory/semantic_memory.py` (replaced with `logger.debug`); also fixed `memory/embeddings.py` and `retrieval/vector_search.py`. Added `scripts/check_no_stdout_pollution.py` CI guard that fails on any stdout-going `print()` in MCP-critical modules.
- **Task 1.3** — `orchestrator/session.py` no longer captures `.cognirepo/sessions` at module-load time; all path resolution is now lazy via `config.paths.get_path()`, so `--project-dir` and `COGNIREPO_DIR` are correctly honoured for session storage.
- **Task 1.4** — `cron/prune_memory.py` FAISS rebuild now writes to the configured project path (via `config.paths.get_path("vector_db/semantic.index")`) instead of a hard-coded relative `./vector_db/` path.

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
