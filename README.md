# CogniRepo

A local cognitive infrastructure layer for AI agents. Any AI tool — Claude, Gemini, Cursor, Copilot, Codex — can plug into CogniRepo to get semantic memory, episodic history, codebase understanding, and intelligent query routing, all stored privately on your machine.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                          Client Layer                            │
│  Claude Desktop (MCP) │ Cursor/Copilot (OpenAI spec) │ CLI/REST │
└───────────────┬─────────────────────────┬────────────────────────┘
                │ stdio (MCP)             │ HTTP/JWT (FastAPI)
┌───────────────▼─────────────────────────▼────────────────────────┐
│                          tools/ layer                            │
│   store_memory │ retrieve_memory │ search_docs │ log_episode     │
└───┬────────────┬────────────────────────┬─────────────────────────┘
    │            │                        │
    ▼            ▼                        ▼
┌────────┐ ┌──────────────┐    ┌─────────────────────────────┐
│ FAISS  │ │ Knowledge    │    │ Orchestrator                │
│ index  │ │ Graph        │    │  classifier → FAST          │──▶ Gemini Flash
│(vector)│ │ (NetworkX)   │    │              BALANCED       │──▶ Gemini Flash
│        │ │              │    │              DEEP           │──▶ Claude Sonnet
│        │ │ Behaviour    │    │                             │
│        │ │ Tracker      │    │  [gRPC sub-queries]         │
└────────┘ └──────────────┘    │  COGNIREPO_MULTI_AGENT=true │
    │            │             └─────────────────────────────┘
    └──────┬─────┘
           ▼
┌──────────────────────┐
│ retrieval/hybrid.py  │  score = 0.5·vector + 0.3·graph + 0.2·behaviour
└──────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────┐
│              .cognirepo/                     │
│  memory/  graph/  index/  sessions/          │
│  archive/  (all local, never leaves disk)    │
└──────────────────────────────────────────────┘
```

---

## Quick Start

### Local

```bash
git clone <repo> && cd cognirepo
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"

cognirepo init --password mypassword
cognirepo index-repo .
cognirepo store-memory "fixed JWT expiry bug in verify_token"
cognirepo retrieve-memory "auth bug"

# Multi-model ask (requires API keys in .env)
cp .env.example .env          # fill in ANTHROPIC_API_KEY / GEMINI_API_KEY
cognirepo ask "why is verify_token slow?" --verbose

# Export specs for Cursor/Copilot
cognirepo export-spec
```

### Docker

```bash
cp .env.example .env          # fill in API keys + COGNIREPO_PASSWORD

docker compose up api          # REST API on :8080
docker compose --profile grpc up          # + gRPC on :50051
docker compose --profile pruner up        # + daily memory pruner
docker compose --profile grpc --profile pruner up   # everything
```

Docs at `http://localhost:8080/docs`

---

## MCP Setup (Claude Desktop)

`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cognirepo": {
      "command": "/path/to/venv/bin/cognirepo",
      "args": ["serve"]
    }
  }
}
```

---

## Cursor / Copilot Setup

```bash
cognirepo export-spec
cp adapters/cursor_mcp_config.json .cursor/mcp.json
# Restart Cursor — CogniRepo tools appear in the tool selector
```

For OpenAI-compatible tools, reference `adapters/openai_tools.json`.

---

## Configuration

`.cognirepo/config.json` — written by `cognirepo init`:

```json
{
  "password_hash": "...",
  "api_port": 8080,
  "retrieval_weights": { "vector": 0.5, "graph": 0.3, "behaviour": 0.2 },
  "models": {
    "FAST":     { "provider": "gemini",    "model": "gemini-2.0-flash" },
    "BALANCED": { "provider": "gemini",    "model": "gemini-2.0-flash" },
    "DEEP":     { "provider": "anthropic", "model": "claude-sonnet-4-6" }
  }
}
```

Key environment variables (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Claude models |
| `GEMINI_API_KEY` | — | Gemini models |
| `OPENAI_API_KEY` | — | OpenAI / Cursor |
| `COGNIREPO_MULTI_AGENT_ENABLED` | `false` | gRPC sub-query delegation |
| `COGNIREPO_CB_RSS_LIMIT_MB` | 80% RAM | OOM circuit breaker |

---

## Multi-Agent Mode

Off by default. Set `COGNIREPO_MULTI_AGENT_ENABLED=true`.

DEEP queries spawn up to 2 FAST sub-queries via gRPC (Gemini Flash) before
calling the primary model. Sub-results land in `.cognirepo/sessions/`.
Depth is one level — sub-agents do not chain.
Requires `cognirepo serve-grpc` (or `--profile grpc`).

---

## Memory Pruning

```bash
cognirepo prune --dry-run --verbose      # preview
cognirepo prune --archive                # prune + save to .cognirepo/archive/
cognirepo prune --aggressive --archive   # lower threshold (0.05)
```

Score formula: `importance × e^(−0.1 × days_old)`. Default threshold: 0.15.

---

## Stack

Python 3.11 · FastAPI · FAISS · NetworkX · sentence-transformers · MCP SDK · gRPC · JWT
