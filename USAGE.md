# CogniRepo — Usage Reference

Complete documentation for every command, API endpoint, Docker service, and configuration option.

---

## Table of Contents

1. [Installation](#installation)
2. [CLI Commands](#cli-commands)
3. [REST API](#rest-api)
4. [MCP Server](#mcp-server)
5. [gRPC Server](#grpc-server)
6. [Docker](#docker)
7. [Multi-Agent Mode](#multi-agent-mode)
8. [Memory Pruning & Circuit Breaker](#memory-pruning--circuit-breaker)
9. [Configuration Reference](#configuration-reference)
10. [Cursor / Copilot Integration](#cursor--copilot-integration)
11. [Adding API Keys](#adding-api-keys)

---

## Installation

### Local

```bash
git clone <repo> && cd cognirepo
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -e ".[dev]"
pip install grpcio grpcio-tools python-dotenv

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

### `cognirepo init`

Scaffold `.cognirepo/` directory structure and write `config.json`.

```bash
cognirepo init
cognirepo init --password mypassword --port 8080
```

Safe to re-run — only backfills missing keys, never overwrites `password_hash`.

Creates:
- `.cognirepo/memory/` — semantic + episodic storage
- `.cognirepo/graph/` — knowledge graph pickle + behaviour JSON
- `.cognirepo/index/` — AST index + FAISS symbol index
- `.cognirepo/sessions/` — gRPC shared session context
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

Search indexed Markdown documentation files.

```bash
cognirepo search-docs "authentication"
cognirepo search-docs "FAISS index format"
```

Fast path: AST reverse index lookup (O(1)).
Fallback: full-text scan of `.md` files under `.cognirepo/docs/`.

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

Walk a Python codebase, extract AST symbols (functions, classes), embed them,
and store in FAISS + knowledge graph.

```bash
cognirepo index-repo .
cognirepo index-repo /path/to/other/project
```

Skips: `venv/`, `.git/`, `__pycache__/`, `node_modules/`, `.tox/`, `dist/`, `build/`.
Output: `{"status": "indexed", "files_indexed": 42, "symbols_found": 387}`

Re-running is safe — unchanged files (same SHA-256) are skipped.

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

| Tier | Score | Default Model |
|---|---|---|
| FAST | 0–6 | gemini-2.0-flash |
| BALANCED | 7–14 | gemini-2.0-flash |
| DEEP | 15+ | claude-sonnet-4-6 |

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

### `cognirepo serve`

Start the MCP stdio server (for Claude Desktop).

```bash
cognirepo serve
```

Reads from stdin, writes to stdout. Claude Desktop manages the process lifecycle.

---

### `cognirepo serve-api`

Start the FastAPI REST server.

```bash
cognirepo serve-api
cognirepo serve-api --host 0.0.0.0 --port 8080 --reload
```

Endpoints:
- `POST /login` — get JWT token
- `POST /memory/store` — store memory
- `POST /memory/retrieve` — retrieve memories
- `POST /episodic/log` — log event
- `GET /episodic/history` — get history
- `GET /health` — health check (no auth required)
- `GET /docs` — Swagger UI

---

### `cognirepo serve-grpc`

Start the gRPC inter-model server (used for multi-agent mode).

```bash
cognirepo serve-grpc
cognirepo serve-grpc --port 50052
```

Services: `QueryService` (SubQuery, SubQueryStream), `ContextService` (PushContext, GetContext, ListSessions).

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

CogniRepo exposes 4 MCP tools over stdio transport:

| Tool | Parameters | Returns |
|---|---|---|
| `store_memory` | `text: str`, `source: str=""` | `{status, text, importance, source}` |
| `retrieve_memory` | `query: str`, `top_k: int=5` | `list[{text, importance, final_score, ...}]` |
| `search_docs` | `query: str` | `list[str]` (file paths) |
| `log_episode` | `event: str`, `metadata: dict={}` | `{status, event, time}` |

Tool schemas are in `server/manifest.json` and exportable via `cognirepo export-spec`.

---

## gRPC Server

Port 50051 by default. Two services:

### QueryService

```python
from rpc.client import CogniRepoClient

with CogniRepoClient(port=50051) as c:
    # Delegate a sub-query to the model router
    resp = c.sub_query(
        query="what does verify_token return on expiry?",
        context_id="q_abc123",
        source_model="claude-sonnet-4-6",
        target_tier="FAST",   # hint: use Gemini Flash
        max_tokens=256,
    )
    print(resp.result, resp.confidence)

    # Streaming version
    for chunk in c.sub_query_stream("explain auth flow", target_tier="FAST"):
        print(chunk.result, end="")
```

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
| `api` | default | 8080 | FastAPI REST server |
| `mcp` | default | stdio | MCP server for Claude Desktop |
| `grpc` | `grpc` | 50051 | gRPC inter-model server |
| `pruner` | `pruner` | — | Daily memory pruning cron |

### Commands

```bash
# Start REST API (always on)
docker compose up -d api

# Start with gRPC (for multi-agent)
docker compose --profile grpc up -d

# Start with pruner
docker compose --profile pruner up -d

# Start everything
docker compose --profile grpc --profile pruner up -d

# View logs
docker compose logs -f api
docker compose logs -f grpc

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
export COGNIREPO_MULTI_AGENT_ENABLED=true
# or in .env: COGNIREPO_MULTI_AGENT_ENABLED=true
```

Requires gRPC server running:

```bash
# Terminal 1
cognirepo serve-grpc

# Terminal 2
COGNIREPO_MULTI_AGENT_ENABLED=true cognirepo ask \
  "design jwt_auth compare verify_token with check_session" --verbose
```

**What happens for a DEEP query:**

1. Classifier assigns DEEP tier
2. Router extracts up to 2 entities from query
3. For each entity: gRPC `SubQuery` to FAST tier (Gemini Flash, ≤256 tokens, 10s timeout)
4. Sub-results stored in `.cognirepo/sessions/<id>.json`
5. Sub-results injected into Claude's system prompt
6. Claude (DEEP) reasons with full context + sub-query results

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
| `api_port` | int | 8080 | FastAPI port |
| `api_url` | string | `http://localhost:8080` | Full API URL |
| `retrieval_weights.vector` | float | 0.5 | Weight for FAISS vector score |
| `retrieval_weights.graph` | float | 0.3 | Weight for graph hop score |
| `retrieval_weights.behaviour` | float | 0.2 | Weight for behaviour hit count |
| `models.FAST.provider` | string | `gemini` | Provider for FAST tier |
| `models.FAST.model` | string | `gemini-2.0-flash` | Model for FAST tier |
| `models.BALANCED.provider` | string | `gemini` | Provider for BALANCED tier |
| `models.BALANCED.model` | string | `gemini-2.0-flash` | Model for BALANCED tier |
| `models.DEEP.provider` | string | `anthropic` | Provider for DEEP tier |
| `models.DEEP.model` | string | `claude-sonnet-4-6` | Model for DEEP tier |
| `circuit_breaker.rss_limit_mb` | float | 80% of RAM | RSS limit before circuit opens |

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Claude API key (for DEEP tier) |
| `GEMINI_API_KEY` | — | Gemini API key (for FAST/BALANCED tier) |
| `OPENAI_API_KEY` | — | OpenAI API key or `"ollama"` for local |
| `OPENAI_BASE_URL` | — | Override endpoint (Ollama: `http://localhost:11434/v1`) |
| `COGNIREPO_MULTI_AGENT_ENABLED` | `false` | Enable gRPC sub-query delegation |
| `COGNIREPO_GRPC_HOST` | `localhost` | gRPC server host |
| `COGNIREPO_GRPC_PORT` | `50051` | gRPC server port |
| `COGNIREPO_GRPC_ENABLED` | `false` | Auto-start gRPC with serve-api |
| `COGNIREPO_CB_RSS_LIMIT_MB` | 80% RAM | Circuit breaker RSS threshold |
| `COGNIREPO_CB_COOLDOWN_SEC` | `30` | Circuit breaker cooldown seconds |
| `COGNIREPO_API_URL` | `http://localhost:8080` | REST base URL for `--via-api` |
| `COGNIREPO_TOKEN` | — | Pre-set JWT (skips password prompt) |
| `COGNIREPO_PASSWORD` | — | Plain password for auto-login (dev only) |

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
