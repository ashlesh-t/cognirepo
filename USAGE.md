# CogniRepo — Usage Reference

Complete documentation for every command, API endpoint, Docker service, and configuration option.

---

## Table of Contents

1. [Installation](#installation)
2. [CLI Commands](#cli-commands)
3. [REST API](#rest-api)
4. [MCP Server](#mcp-server)
6. [Docker](#docker)
7. [Multi-Agent Mode](#multi-agent-mode)
8. [Memory Pruning & Circuit Breaker](#memory-pruning--circuit-breaker)
9. [Configuration Reference](#configuration-reference)
10. [Cursor / Copilot Integration](#cursor--copilot-integration)
11. [Adding API Keys](#adding-api-keys)

---

## Installation

### pip (recommended)

```bash
pip install cognirepo                      # core — Python only, no extras
pip install cognirepo[languages]           # + multi-language AST indexing (JS, TS, Java, Go, Rust, C++)
pip install cognirepo[security]            # + encryption at rest (Fernet + OS keychain)
pip install cognirepo[dev]                 # + dev tools (pytest, bandit, etc.)
pip install cognirepo[languages,security]  # everything
```

### From source

```bash
git clone https://github.com/ashlesh-t/cognirepo && cd cognirepo
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -e ".[dev,languages]"

# One-time setup
cognirepo init --password yourpassword --port 8080
```

### Docker

```bash
cp .env.example .env    # fill in API keys
docker compose up api   # REST API on :8080
```

---

## CLI Commands

All commands support `--via-api` (routes through REST instead of in-process) and
`--api-url URL` (override REST base URL).


Start the interactive REPL (alias: `cognirepo` with no subcommand).

```bash
cognirepo chat                                        # start REPL
cognirepo chat --model claude-opus-4-6               # force model for all queries
```

On startup the REPL shows:
- Project name, memory count, graph node count
- Active tier → model routing table
- API keys detected (warns if none set)
- Multi-agent status

Type `/help` inside the REPL to list all slash commands.
See [docs/CLI.md](docs/CLI.md) for the full REPL reference.

---

### `cognirepo migrate-config`

Rename legacy tier keys in `.cognirepo/config.json` in-place (v0.x → v1.0 migration).

```bash
cognirepo migrate-config
```

Renames legacy v0.x tier keys to their v1.0 equivalents (e.g. the old name → STANDARD, COMPLEX, EXPERT).
Creates a `.cognirepo/config.json.bak` backup before modifying.
Raises `ConfigMigrationError` on unknown keys so you can inspect before proceeding.

---

### `cognirepo setup-env`

Interactive wizard to set and verify API keys (also reachable from `cognirepo init`).

```bash
cognirepo setup-env                # interactive prompt for all supported API keys
cognirepo setup-env --skip-verify  # write keys but skip API verification calls (CI)
```

Supported providers: Anthropic, Gemini, OpenAI/Ollama, Grok/xAI.
Keys are written to `.env` in the project root. Existing keys are not overwritten
unless you confirm.

---

### `cognirepo init`

Scaffold `.cognirepo/` directory structure and write `config.json`.

**Interactive mode (default):** launches a powerlevel10k-style wizard that asks:

1. Project name (used to namespace your data in Claude/Gemini)
2. Multi-model routing (QUICK→local, STANDARD→Gemini/Grok, COMPLEX→Gemini/Sonnet, EXPERT→Claude Opus)
4. Redis session cache
5. Encryption at rest (Fernet — auto-installs `cognirepo[security]`)
6. Extended language parsers (auto-installs `cognirepo[languages]`)
7. **MCP integration** — Claude, Gemini, Both, or Skip
   - Writes `.claude/CLAUDE.md` + `.claude/settings.json` (project-locked connector)
   - Writes `.gemini/COGNIREPO.md` + `.gemini/settings.json`
8. REST API port + password

```bash
cognirepo init                              # interactive wizard (default when TTY)
cognirepo init --no-index                   # skip automatic post-init indexing
cognirepo init --non-interactive            # skip wizard entirely (uses defaults)
cognirepo init --password mypassword --port 8080   # set credentials non-interactively
cognirepo init --non-interactive --no-index # CI / scripting — no prompt, no index
cognirepo init --daemon                     # run post-init file watcher in background
```

After `init` completes, the repo is indexed automatically unless `--no-index` is passed.
Safe to re-run — only backfills missing keys.

Creates:
- `.cognirepo/memory/` — semantic + episodic storage
- `.cognirepo/graph/` — knowledge graph pickle + behaviour JSON
- `.cognirepo/index/` — AST index + FAISS symbol index
- `.cognirepo/sessions/` — conversation sessions
- `.cognirepo/errors/` — timestamped error logs
- `.claude/` — Claude Code project config (if MCP target selected)
- `.gemini/` — Gemini CLI project config (if MCP target selected)
- `vector_db/` — FAISS semantic index

---

### `cognirepo store-memory`

Save text as a semantic memory (FAISS vector + metadata).

```bash
cognirepo store-memory "fixed JWT expiry bug in verify_token"
cognirepo store-memory "refactored auth middleware to use bcrypt" --source "git-commit"
```

**Options:**
- `--source TEXT` — label for the memory origin (default: empty)

**Output:** `{"status": "stored", "text": "...", "importance": 0.72, "source": "..."}`

Importance is scored by text length + keyword density (bug, fix, auth, etc.).

---

### `cognirepo retrieve-memory`

Hybrid similarity search: FAISS vector + knowledge graph proximity + behaviour weight.

```bash
cognirepo retrieve-memory "auth bug"
cognirepo retrieve-memory "jwt token expiry" --top-k 10
cognirepo retrieve-memory "auth bug" --via-api
```

**Options:**
- `--top-k N` — number of results to return (default: 5)

**Output:** list of memory records with `text`, `importance`, `final_score`, `vector_score`, `graph_score`.

Score formula: `final = 0.5·vector + 0.3·graph + 0.2·behaviour`

---

### `cognirepo search-docs`

Search all Markdown documentation files recursively for the query string.
Returns **content snippets** (±2 lines of context) alongside the file path and line number
— similar to `grep -C 2`.

```bash
cognirepo search-docs "authentication"
cognirepo search-docs "JWT expiry"
```

**Output:**
```
./docs/auth.md
──────────────
  Line 42:
    ## Token Expiry
    JWT tokens expire after 24 hours. Use Bearer scheme.
    Refresh tokens are not supported in v1.0.

./USAGE.md
──────────
  Line 18:
    TOKEN=$(curl ... | jq -r .access_token)
```

**Search strategy:** AST reverse-index fast path for known tokens, then full recursive
`os.walk` from the project root (covers the entire repo tree, not just `.cognirepo/docs/`).

---

### `cognirepo log-episode`

Append a timestamped event to the episodic log.

```bash
cognirepo log-episode "deployed auth service to production"
cognirepo log-episode "fixed timeout bug" --meta '{"ticket": "AUTH-42", "env": "prod"}'
```

**Options:**
- `--meta JSON` — JSON metadata object

---

### `cognirepo history`

Print recent episodic events, newest first.

```bash
cognirepo history
cognirepo history --limit 50
```

---

### `cognirepo index-repo`

Walk a codebase, extract AST symbols (functions, classes), embed them,
and store in FAISS + knowledge graph.

**Path validation:** exits with code 1 and a clear error message if the directory
does not exist — no silent 0-file success.

```bash
cognirepo index-repo .
cognirepo index-repo /path/to/other/project

# Invalid path — explicit error, non-zero exit:
cognirepo index-repo /nonexistent   # Error: Directory does not exist: /nonexistent

# Run the file watcher in the background (returns immediately):
cognirepo index-repo . --daemon
cognirepo index-repo . -d

# Index only, no watcher (useful in CI):
cognirepo index-repo . --no-watch
```

Indexes all supported file types automatically. Install `cognirepo[languages]` for
JS, TS, Java, Go, Rust, and C++ support beyond Python.

Skips: `venv/`, `.git/`, `__pycache__/`, `node_modules/`, `.tox/`, `dist/`, `build/`.
Output: `{"status": "indexed", "files_indexed": 42, "symbols_found": 387, "languages": {...}}`

Re-running is safe — unchanged files (same SHA-256) are skipped.

**Flags**

| Flag | Description |
|------|-------------|
| `--no-watch` | Exit immediately after indexing (no watcher) |
| `--daemon` / `-d` | Fork watcher to background; prints PID and log path |

> **Platform note:** The background file watcher (`--daemon`) uses `fcntl` and is **Linux-only**.
> On macOS or Windows, `--daemon` exits with code 2 and a friendly message — use `--no-watch` for CI.

---

### `cognirepo serve`

Start the MCP stdio server (connects to Claude Code, Gemini CLI, Cursor, etc.).

```bash
# Simple start (uses current directory as project root):
cognirepo serve

# Project-locked start (required for multi-project / multi-team setups):
cognirepo serve --project-dir /abs/path/to/project
```

The `--project-dir` flag is the key to data isolation. When you have two projects open in
Claude simultaneously, each must have its own MCP server instance locked to its directory:

```json
// .claude/settings.json  (generated automatically by cognirepo init)
{
  "mcpServers": {
    "cognirepo-alpha": {
      "command": "cognirepo",
      "args": ["serve", "--project-dir", "/projects/alpha"],
      "env": {}
    },
    "cognirepo-beta": {
      "command": "cognirepo",
      "args": ["serve", "--project-dir", "/projects/beta"],
      "env": {}
    }
  }
}
```

`cognirepo init` writes this automatically — you do not need to edit it manually.

---

### `cognirepo wait-api`

Poll the REST API's `/ready` endpoint until the server is accepting connections.
Use this before cURLing `/login` to avoid `JSONDecodeError` from hitting the server
before it has fully started.

```bash
# Start server in background, then wait before curling:
cognirepo wait-api --timeout 30

TOKEN=$(curl -s -X POST http://localhost:8080/login \
  -H "Content-Type: application/json" \
  -d '{"password":"changeme"}' | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

**Options:**
- `--timeout N` — max seconds to wait (default: 30)
- `--interval N` — poll interval in seconds (default: 0.3)

Exits 0 when ready, 1 on timeout.

---

### `cognirepo list`

Manage background watcher daemon processes.

```bash
# Show all running watchers:
cognirepo list
cognirepo list -p

# Interactively tail a watcher's log (Ctrl+C to stop viewing):
cognirepo list -n <PID_OR_NAME> --view

# Stop a watcher:
cognirepo list -n <PID_OR_NAME> --stop
```

**Example workflow**

```bash
$ cognirepo index-repo . --daemon
[cognirepo] Watcher started in background (PID 94312)
[cognirepo] Name : watcher-cognirepo-1743350400
[cognirepo] Log  : .cognirepo/watchers/watch_1743350400.log
[cognirepo] View : cognirepo list -n 94312 --view

$ cognirepo list
PID      NAME                                 PATH                                     STARTED              STATUS
94312    watcher-cognirepo-1743350400         /home/user/my_works/cognirepo            2026-03-30 12:00:00  running

$ cognirepo list -n 94312 --view
[cognirepo] Viewing logs for watcher 'watcher-cognirepo-1743350400' (PID 94312)
[cognirepo] Log: .cognirepo/watchers/watch_1743350400.log  |  Ctrl+C to stop viewing

[watcher] re-indexed api/routes/graph.py
...

$ cognirepo list -n 94312 --stop
[cognirepo] Sent SIGTERM to watcher '94312'.
```

PID files are stored under `.cognirepo/watchers/<pid>.json` and cleaned up automatically when the process exits.

---

### `cognirepo ask`

Route a natural-language query through the full orchestration pipeline:
classify → build context → call model → post-process.

```bash
cognirepo ask "why is verify_token slow?"
cognirepo ask "compare jwt_auth with session_auth" --verbose
cognirepo ask "implement a rate limiter" --model claude-opus-4-6
cognirepo ask "list all functions in auth.py" --top-k 10
```

**Options:**
- `--model MODEL_ID` — force a specific model (tier still computed for routing info)
- `--top-k N` — memories to retrieve for context (default: 5)
- `--verbose` — print tier, score, signals before the answer

**Tier routing (default models):**

| Tier | Score | Default Model | Provider | Use case |
|------|-------|---------------|----------|----------|
| QUICK | ≤2 | local-resolver | local | Single-token / docs — zero-API |
| STANDARD | ≤4 | claude-haiku-4-5 | Anthropic | Factual lookup, single symbol |
| COMPLEX | ≤9 | claude-sonnet-4-6 | Anthropic | Moderate reasoning |
| EXPERT | >9 | claude-opus-4-6 | Anthropic | Cross-file, architectural |

On API error: user sees a friendly one-liner; full traceback saved to `.cognirepo/errors/<date>.log`.
Override models in `.cognirepo/config.json` → `models` block.

**Requires:** at least one API key set (`ANTHROPIC_API_KEY` or `GEMINI_API_KEY`).

---

### `cognirepo prune`

Score all semantic memories by `importance × e^(−0.1 × days_old)` and remove
entries below threshold. Also prunes orphan/cold nodes from the knowledge graph.

```bash
cognirepo prune --dry-run --verbose        # preview without changes
cognirepo prune                             # prune with default threshold (0.15)
cognirepo prune --archive                  # save pruned entries to .cognirepo/archive/
cognirepo prune --aggressive               # threshold 0.05 (keeps less)
cognirepo prune --threshold 0.25 --archive # custom threshold + archive
```

**Options:**
- `--dry-run` — report only, no files changed
- `--aggressive` — threshold 0.05 instead of 0.15
- `--archive` — save pruned entries to `.cognirepo/archive/<timestamp>.json`
- `--threshold FLOAT` — explicit threshold override
- `--verbose` — print each pruned entry with score and age

Blocked automatically if the circuit breaker is OPEN (RSS too high).

---



```bash
```

Endpoints:
- `POST /login` — get JWT token (returns `{"access_token": "...", "token_type": "bearer"}`)
- `GET /ready` — lightweight readiness probe (no auth, poll before `/login`)
- `GET /health` — health check with circuit breaker state (no auth required)
- `GET /status/detailed` — full diagnostics JSON (no auth): uptime, FAISS size, graph stats, circuit breaker state, multi-agent flag
- `GET /metrics` — Prometheus metrics in text format (no auth, requires `cognirepo[dev]`)
- `POST /memory/store` — store memory
- `POST /memory/retrieve` — retrieve memories
- `POST /episodic/log` — log event
- `GET /episodic/history` — get history
- `GET /docs` — Swagger UI

### Observability Dashboard

Import `deploy/grafana/cognirepo.json` into Grafana (≥ 10.0) to get a pre-built
dashboard wired to the Prometheus metrics:

- **HTTP**: request rate, p50/p95 latency per route
- **Memory & Graph**: FAISS vector count, graph nodes/edges
- **Circuit Breaker**: 0 = CLOSED (green), 1 = HALF_OPEN (yellow), 2 = OPEN (red)
- **Retrieval**: p95 latency per signal (vector / graph / bm25), memory op rate

```bash
# Quick check via /status/detailed (no auth needed)
curl http://localhost:8080/status/detailed | python3 -m json.tool
```

**Safe curl pattern** (use `cognirepo wait-api` or poll `/ready`):
```bash
cognirepo wait-api                   # blocks until /ready returns 200
TOKEN=$(curl -s -X POST http://localhost:8080/login \
  -H "Content-Type: application/json" \
  -d '{"password":"changeme"}' | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

---



```bash
```

Services: `QueryService` (SubQuery, SubQueryStream), `ContextService` (PushContext, GetContext, ListSessions).

---

### `cognirepo doctor`

Run a system health check and report the status of all CogniRepo components.

```bash
cognirepo doctor                    # run health check
cognirepo doctor --verbose          # show file paths and optional component details
cognirepo doctor --release-check    # also scan docs for legacy v0.x refs and old tier names
```

Example output:

```
CogniRepo doctor — v1.0.0

  ✓  .cognirepo/ — config valid · project: my-project
  ✓  FAISS index — 47 memories
  ✓  Knowledge graph — 1,832 nodes · 4,218 edges
  ✓  AST index — 312 symbols across 23 files
  ✓  Episodic log — 89 events
  ✓  Language support — Python, JS, TS, Java, Go, Rust, C++
  ✗  Model API keys — no keys configured
       Set at least one: ANTHROPIC_API_KEY · GEMINI_API_KEY · OPENAI_API_KEY · GROK_API_KEY
  ✓  Circuit breaker — CLOSED (RSS: 412 MB / 6,553 MB limit)
  ✓  BM25 backend — python

  1 issue found.
```

Exit code: `0` = all checks pass, `1` = at least one issue found.

---

### `cognirepo export-spec`

Read `server/manifest.json` and write:
- `adapters/openai_tools.json` — OpenAI function-calling format
- `adapters/cursor_mcp_config.json` — Cursor `.cursor/mcp.json` format

```bash
cognirepo export-spec
```

---

## REST API

All endpoints except `/login` and `/health` require `Authorization: Bearer <token>`.

### Authentication

```bash
# Get token
curl -X POST http://localhost:8080/login \
  -H "Content-Type: application/json" \
  -d '{"password": "yourpassword"}'
# → {"access_token": "eyJ...", "token_type": "bearer"}

TOKEN=eyJ...
```

### Store memory

```bash
curl -X POST http://localhost:8080/memory/store \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "fixed JWT expiry bug", "source": "git"}'
```

### Retrieve memories

```bash
curl -X POST http://localhost:8080/memory/retrieve \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "auth bug", "top_k": 5}'
```

### Log episode

```bash
curl -X POST http://localhost:8080/episodic/log \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"event": "deployed service", "metadata": {"env": "prod"}}'
```

### Get history

```bash
curl "http://localhost:8080/episodic/history?limit=20" \
  -H "Authorization: Bearer $TOKEN"
```

### Health check

```bash
curl http://localhost:8080/health
# → {"status": "ok", "circuit_breaker": "CLOSED"}
```

---

## MCP Server

CogniRepo exposes 12 MCP tools over stdio transport:

| Tool | Parameters | Returns |
|---|---|---|
| `store_memory` | `text: str`, `source: str=""` | `{status, text, importance, source}` |
| `retrieve_memory` | `query: str`, `top_k: int=5` | `list[{text, importance, final_score, ...}]` |
| `search_docs` | `query: str` | `list[str]` (file paths with snippets) |
| `log_episode` | `event: str`, `metadata: dict={}` | `{status, event, time}` |
| `lookup_symbol` | `name: str` | `{file, line, kind}` |
| `who_calls` | `function_name: str` | `list[str]` (caller names) |
| `subgraph` | `entity: str`, `depth: int=1` | neighbourhood nodes/edges |
| `episodic_search` | `query: str`, `limit: int=10` | BM25-ranked event list |
| `graph_stats` | _(none)_ | `{nodes, edges, ...}` |
| `semantic_search_code` | `query: str`, `top_k: int=5` | FAISS-ranked code symbols |
| `dependency_graph` | `file: str` | import dependency map |
| `context_pack` | `query: str` | packed code + memory bundle |

Tool schemas are in `server/manifest.json` and exportable via `cognirepo export-spec`.

---


### Port selection and on/off switch

| Environment variable | Default | Purpose |
|---|---|---|

```bash

# Use a custom port

```

and the server does not need to be running. All queries are handled by the primary
model directly.

### Health endpoint



The CI pipeline polls `health()` before running integration tests to avoid
races during server startup.

### Sub-query retry behaviour

`sub_query()` retries up to **3 times** with exponential backoff (0.5 s, 1 s, 2 s)
on `UNAVAILABLE` and `DEADLINE_EXCEEDED` errors.  Non-retryable errors (e.g.
`INTERNAL`) surface immediately.  A `trace_id` is auto-generated (or you can
supply one) and propagated through gRPC metadata for log correlation.

```python
resp = c.sub_query(
    "who calls verify_token?",
    trace_id="req-abc-123",   # correlate logs across services
    timeout=10.0,             # per-attempt deadline
)
```

### QueryService


### ContextService

```python
with CogniRepoClient() as c:
    # Push partial reasoning into shared session
    c.push_context("q_abc123", "step_1", "JWT uses HS256 algorithm")

    # Pull context (any model can read)
    entries = c.get_context("q_abc123")
    print(entries)  # {"step_1": "JWT uses HS256 algorithm"}

    # List active sessions
    print(c.list_sessions(limit=10))
```

Session data persists in `.cognirepo/sessions/<context_id>.json`.

---

## Docker

### Services

| Service | Profile | Port | Purpose |
|---|---|---|---|
| `mcp` | default | stdio | MCP server for Claude Desktop |
| `pruner` | `pruner` | — | Daily memory pruning cron |

### Commands

```bash
# Start REST API (always on)
docker compose up -d api


# Start with pruner
docker compose --profile pruner up -d

# Start everything

# View logs
docker compose logs -f api

# Run CLI commands inside container
docker compose exec api cognirepo retrieve-memory "auth bug"
docker compose exec api cognirepo prune --dry-run

# Stop all
docker compose down

# Stop and remove volumes (DESTROYS ALL DATA)
docker compose down -v
```

### Volumes

| Volume | Mount | Contents |
|---|---|---|
| `cognirepo_data` | `/app/.cognirepo` | memories, graph, index, sessions |
| `cognirepo_vectors` | `/app/vector_db` | FAISS semantic index |

To back up:
```bash
docker run --rm -v cognirepo_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/cognirepo_backup.tar.gz /data
```

To restore:
```bash
docker run --rm -v cognirepo_data:/data -v $(pwd):/backup \
  alpine tar xzf /backup/cognirepo_backup.tar.gz -C /
```

### Inside Docker — working with CogniRepo

```bash
# Shell into running container
docker compose exec api bash

# Index a mounted repo
docker compose run --rm -v /path/to/your/project:/project api \
  cognirepo index-repo /project

# Store a memory
docker compose exec api cognirepo store-memory "fixed auth bug"

# Ask a question (API keys must be in .env)
docker compose exec api cognirepo ask "why is auth slow?" --verbose
```

---

## Multi-Agent Mode

**Off by default.** Enable with:

```bash
```


```bash
# Terminal 1

# Terminal 2
  "design jwt_auth compare verify_token with check_session" --verbose
```

**What happens for an EXPERT query:**

1. Classifier assigns EXPERT tier
2. Router extracts up to 2 entities from query
3. For each entity: gRPC `SubQuery` to STANDARD tier (≤256 tokens, 10s timeout)
4. Sub-results stored in `.cognirepo/sessions/<id>.json` under `sub_queries[]`
5. Sub-results injected into Claude's system prompt
6. Claude Opus (EXPERT) reasons with full context + sub-query results
7. REPL shows a greyed-out sub-agent panel after the primary response (`/agents` to inspect)

**Agents involved:** 1 orchestrator + up to 2 sub-agents. Total: ≤3 model calls per query.
**Failure mode:** sub-queries are best-effort; failures are silently dropped, primary model still runs.

---

## Memory Pruning & Circuit Breaker

### Pruning schedule

**Cron (local):**
```bash
# Add to crontab -e
0 3 * * * cd /path/to/cognirepo && venv/bin/python -m cron.prune_memory --archive
```

**Docker:** use `--profile pruner` (runs daily at midnight via sleep loop).

### Circuit Breaker

Prevents OOM by monitoring process RSS. States: `CLOSED` → `OPEN` → `HALF_OPEN`.

Thresholds:

```bash
# Via environment
export COGNIREPO_CB_RSS_LIMIT_MB=3000   # trip at 3 GB RSS
export COGNIREPO_CB_COOLDOWN_SEC=60     # wait 60s before retrying

# Via config.json
{
  "circuit_breaker": { "rss_limit_mb": 3000 }
}
```

When OPEN:
- `store_memory` returns `{"status": "error", "reason": "circuit_open"}` (no crash)
- `retrieve_memory` returns empty list
- `prune` skips the run
- `/health` returns `{"circuit_breaker": "OPEN"}`

Manual reset (e.g. after GC or memory freed):

```python
from memory.circuit_breaker import get_breaker
get_breaker().reset()
```

---

## Configuration Reference

### `.cognirepo/config.json`

| Key | Type | Default | Description |
|---|---|---|---|
| `password_hash` | string | — | bcrypt hash of API password |
| `api_url` | string | `http://localhost:8080` | Full API URL |
| `retrieval_weights.vector` | float | 0.5 | Weight for FAISS vector score |
| `retrieval_weights.graph` | float | 0.3 | Weight for graph hop score |
| `retrieval_weights.behaviour` | float | 0.2 | Weight for behaviour hit count |
| `models.QUICK.provider` | string | `local` | Provider for QUICK tier |
| `models.QUICK.model` | string | `local-resolver` | Model for QUICK tier |
| `models.STANDARD.provider` | string | `anthropic` | Provider for STANDARD tier |
| `models.STANDARD.model` | string | `claude-haiku-4-5` | Model for STANDARD tier |
| `models.COMPLEX.provider` | string | `anthropic` | Provider for COMPLEX tier |
| `models.COMPLEX.model` | string | `claude-sonnet-4-6` | Model for COMPLEX tier |
| `models.EXPERT.provider` | string | `anthropic` | Provider for EXPERT tier |
| `models.EXPERT.model` | string | `claude-opus-4-6` | Model for EXPERT tier |
| `circuit_breaker.rss_limit_mb` | float | 80% of RAM | RSS limit before circuit opens |
| `idle_ttl_seconds` | int | `600` | Seconds of MCP inactivity before heavy resources (embedding model, graph, indexer) are evicted from RAM. Set to `0` to disable. |

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Claude API key (for STANDARD/COMPLEX/EXPERT tiers) |
| `GEMINI_API_KEY` | — | Gemini API key (alternative STANDARD/COMPLEX provider) |
| `OPENAI_API_KEY` | — | OpenAI API key or `"ollama"` for local |
| `OPENAI_BASE_URL` | — | Override endpoint (Ollama: `http://localhost:11434/v1`) |
| `COGNIREPO_JWT_SECRET` | — | JWT signing secret — replaces OS keychain in CI/Docker |
| `COGNIREPO_PASSWORD_HASH` | — | Bcrypt password hash — replaces OS keychain in CI/Docker |
| `COGNIREPO_CB_RSS_LIMIT_MB` | 80% RAM | Circuit breaker RSS threshold |
| `COGNIREPO_CB_COOLDOWN_SEC` | `30` | Circuit breaker cooldown seconds |
| `COGNIREPO_API_URL` | `http://localhost:8080` | REST base URL for `--via-api` |
| `COGNIREPO_TOKEN` | — | Pre-set JWT (skips password prompt) |
| `COGNIREPO_PASSWORD` | — | Plain password for auto-login (dev only) |
| `COGNIREPO_DIR` | — | Override `.cognirepo/` project storage directory (useful in CI and containers) |
| `COGNIREPO_GLOBAL_DIR` | `~/.cognirepo` | Override global user-memory storage directory (test isolation + containers) |

**Docker note:** The OS keychain is not available in containers. Pass secrets via environment variables:

```yaml
# docker-compose.yml
environment:
  - COGNIREPO_JWT_SECRET=${COGNIREPO_JWT_SECRET}
  - COGNIREPO_PASSWORD_HASH=${COGNIREPO_PASSWORD_HASH}
```

---

## Storage Encryption

CogniRepo can encrypt all data under `.cognirepo/` at rest using Fernet symmetric
encryption. The key is stored in your OS keychain — never written to disk.

### Enable

Set in `.cognirepo/config.json`:

```json
{ "storage": { "encrypt": true } }
```

### Requirements

```bash
pip install cognirepo[security]
```

### What gets encrypted

- `.cognirepo/vector_db/metadata.json`
- `.cognirepo/graph/graph.pkl`
- `.cognirepo/episodic/episodic.json`
- `.cognirepo/sessions/*.json`

FAISS index files (`.index`) are binary and are not encrypted (structural limitation of the FAISS format).

### Key management

The encryption key is stored in your OS keychain under service name `cognirepo`.
In CI or Docker where no keychain is available, set:

```bash
COGNIREPO_ENCRYPTION_KEY=<base64-fernet-key>
```

Generate a key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## Cursor / Copilot Integration

```bash
# 1. Generate spec files
cognirepo export-spec

# 2a. Cursor — copy to project root
cp adapters/cursor_mcp_config.json .cursor/mcp.json
# Restart Cursor; tools appear in tool selector

# 2b. OpenAI / GitHub Copilot
# Reference adapters/openai_tools.json in your system prompt or tool config

# 2c. Ollama / LM Studio (OpenAI-compatible)
export OPENAI_BASE_URL=http://localhost:11434/v1
export OPENAI_API_KEY=ollama
cognirepo ask "explain auth flow" --verbose
```

---

## Adding API Keys

```bash
# Copy example
cp .env.example .env

# Edit .env
ANTHROPIC_API_KEY=sk-ant-api03-...
GEMINI_API_KEY=AIzaSy...
# OPENAI_API_KEY=sk-...  (optional)

# Load in shell (or use python-dotenv automatically)
source .env   # bash/zsh
# or: set -a && source .env && set +a
```

In Docker, keys are passed via `docker-compose.yml` `environment:` block from your host `.env`.

---

## File Layout

```
.cognirepo/
  config.json              runtime config (password hash, ports, weights)
  memory/
    semantic.json          FAISS metadata (text + importance per vector)
    semantic_metadata.json same, for vector_db layer
    episodic.json          linked-list event log
  graph/
    graph.pkl              NetworkX DiGraph (pickled)
    behaviour.json         per-symbol hit counts + query history
  index/
    ast_index.json         AST index metadata + reverse symbol lookup
    ast.index              FAISS AST symbol index (IndexIDMap2)
    ast_metadata.json      FAISS metadata for AST symbols
  sessions/
    <context_id>.json      gRPC shared session context
  archive/
    pruned_<ts>.json       archived memories (from --archive flag)

vector_db/
  semantic.index           FAISS semantic memory index (IndexFlatL2)

adapters/
  openai_tools.json        OpenAI function-calling format
  cursor_mcp_config.json   Cursor .cursor/mcp.json format

server/
  manifest.json            MCP tool schemas (auto-generated)
```
