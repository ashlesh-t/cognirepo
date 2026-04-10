You are a senior principal engineer doing an architectural planning session for CogniRepo, a local cognitive infrastructure layer for AI agents (Claude, Gemini, Cursor, Copilot). It is written in pure Python.

## Current System State (Deploy Readiness: 7.5/10)

### Subsystem scores:
- Part A — Core Memory (FAISS + graph + episodic + AST index): 8.5/10
  - Gaps: no structured logging, no metrics endpoint, stale data cleanup incomplete, multi-language AST indexing partial
- REST API: 8/10 — no rate limiting
- MCP Server (12 tools): 8/10 — solid
- CLI (cognirepo commands): 8/10 — Linux daemon only, Windows untested
- Part B — Model Routing (classifier + tiers): 6/10 — QUICK tier needs Grok API key, fallback chain untested in CI
- gRPC (inter-model comms): 5/10 — off-by-default, untested in CI, no failover

### Tech stack:
Python, FastAPI, ChromaDB, NetworkX, tree-sitter, FAISS, Fernet encryption, JWT (OS keychain), Anthropic SDK, Gemini SDK, gRPC, MCP protocol, rank-bm25, Bandit/Snyk/Trivy/TruffleHog in CI.

---

## Target: Bring entire system to 10/10

### Part A — Complete these gaps first (priority order):
1. Structured logging (JSON, log levels, correlation IDs across all subsystems)
2. Metrics endpoint (Prometheus-compatible `/metrics` — memory ops, retrieval latency, index size)
3. Rate limiting on REST API (token bucket per client)
4. Multi-language AST indexing (tree-sitter grammars: Python ✓, JS/TS, Go, Rust, Java)
5. Stale data pruning correctness + scheduled auto-prune
6. Windows CI path for daemon (or clean graceful degradation documented)
7. Circuit breaker generalized (not just RSS)
8. Wheel build verified end-to-end + PyPI publish-ready checklist

### Part B — CogniRepo CLI (interactive, typed `cognirepo` to launch):
Design and implement an interactive CLI experience that:
- Launches when user types `cognirepo` (no subcommand) — opens a REPL/interactive shell
- Looks and feels like the Claude CLI or Gemini CLI (colored output, spinner, streaming responses, session context)
- Built with `rich` + `prompt_toolkit` (or equivalent)
- Has two capability tiers:

**Tier 1 — No external API key needed (offline/local):**
  - Answer any question about CogniRepo usage, commands, architecture, MCP tools, configuration
  - Powered by embedded knowledge (docs, USAGE.md, ARCHITECTURE.md baked into a local retrieval index at install time)
  - Uses CogniRepo's own Part A retrieval (BM25 + graph) to answer these queries — dogfooding
  - Simple factual queries answered instantly with no LLM call

**Tier 2 — With API key (Claude/Gemini):**
  - Complex queries or querries on cognirepo un answerable by tier1 architectuire, HLD generation, architecture plans, multi-step reasoning
  - Model routing based on complexity classifier (signal-based, rule-driven):
    - QUICK tier (≤2 signals): local/fast model or Gemini Flash
    - STANDARD tier (≤4): Claude Haiku or Gemini Flash
    - COMPLEX tier (≤9): Claude Sonnet
    - EXPERT tier (>9): Claude Opus or Gemini Pro
  - Inter-model communication via gRPC for multi-agent workflows
  - Streaming output to terminal
  - Session memory (episodic) — remembers context within a session

**Explicitly NOT in scope (future):**
  - Code editing / implementation (no Aider/Cursor-style file writes)
  - Autonomous agent loops

### CLI UX requirements:
- `/help` — command palette
- `/model` — show/switch active model tier
- `/status` — show daemon health, index stats
- `/history` — session history
- `/clear` — clear session
- `Ctrl+C` graceful exit
- Config file at `~/.cognirepo/cli_config.toml`

---

## Deliverable

Produce a complete, sprint-by-sprint execution plan with:

1. **Phase 1: Part A Completion** — all gaps closed, 10/10 on core
2. **Phase 2: CogniRepo CLI — Foundation** — REPL shell, Tier 1 (local knowledge, no API key)
3. **Phase 3: CogniRepo CLI — Model Routing + gRPC** — Tier 2, complexity classifier, inter-model comms, streaming
4. **Phase 4: Hardening + OSS Release** — CI coverage for all new paths, observability, PyPI publish

For each sprint include:
- Goals
- Specific tasks (numbered)
- Files to create/modify
- Acceptance criteria / definition of done
- Estimated effort (days)
- Risk flags

Output as a structured markdown document titled `EXECUTION_PLAN_v3.md`.
Assume: pure Python, no new language splits, C++ BM25 extension stays optional with Python fallback, all new code must have tests.