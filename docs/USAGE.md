# CogniRepo — Usage Reference

Complete documentation for every command, MCP tool, and configuration option.

---

## Table of Contents

1. [Installation](#installation)
2. [CLI Commands](#cli-commands)
3. [MCP Server](#mcp-server)
4. [Organization Management](#organization-management)
5. [Docker](#docker)
6. [Memory Pruning & Circuit Breaker](#memory-pruning--circuit-breaker)
7. [Configuration Reference](#configuration-reference)
8. [Cursor / Copilot Integration](#cursor--copilot-integration)
9. [Adding API Keys](#adding-api-keys)

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
cognirepo init
```

### Docker

```bash
cp .env.example .env    # fill in API keys
docker compose up mcp   # Pure MCP server via stdio
```

---

## CLI Commands

### `cognirepo init`

Scaffold `.cognirepo/` directory structure and write `config.json`.

**Interactive mode (default):** launches a powerlevel10k-style wizard that asks:

1. Project name (used to namespace your data in Claude/Gemini)
2. Multi-model routing (QUICK→local, STANDARD→Gemini/Grok, COMPLEX→Gemini/Sonnet, EXPERT→Claude Opus)
3. Encryption at rest (Fernet — auto-installs `cognirepo[security]`)
4. Extended language parsers (auto-installs `cognirepo[languages]`)
5. **MCP integration** — Claude, Gemini, Both, or Skip
   - Writes `.claude/CLAUDE.md` + `.claude/settings.json` (project-locked connector)
   - Writes `.gemini/COGNIREPO.md` + `.gemini/settings.json`

```bash
cognirepo init                              # interactive wizard (default when TTY)
cognirepo init --no-index                   # skip automatic post-init indexing
cognirepo init --non-interactive            # skip wizard entirely (uses defaults)
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

### `cognirepo index-repo`

Walk a codebase, extract AST symbols (functions, classes), embed them,
and store in FAISS + knowledge graph.

```bash
cognirepo index-repo .
cognirepo index-repo /path/to/other/project

# Run the file watcher in the background (returns immediately):
cognirepo index-repo . --daemon

# Index only, no watcher (useful in CI):
cognirepo index-repo . --no-watch
```

Indexes all supported file types automatically. Install `cognirepo[languages]` for
JS, TS, Java, Go, Rust, and C++ support beyond Python.

---

### `cognirepo summarize`

Generate hierarchical architectural summaries (Level 1: File, Level 2: Dir, Level 3: Repo).
Uses LLM to rolling-summarize your codebase.

```bash
cognirepo summarize
```

Summaries are stored in `.cognirepo/index/summaries.json` and exposed via the `architecture_overview` MCP tool.

---

### `cognirepo serve`

Start the MCP stdio server (connects to Claude Code, Gemini CLI, Cursor, etc.).

```bash
# Simple start (uses current directory as project root):
cognirepo serve

# Project-locked start (required for multi-project / multi-team setups):
cognirepo serve --project-dir /abs/path/to/project
```

---

### `cognirepo org`

Manage local repository organizations for cross-repo context sharing.

```bash
cognirepo org create my-org
cognirepo org link my-org .
cognirepo org list
```

---

## Organization Management

Organizations allow an agent working in Repo A to query findings, symbols, and context
from Repo B if both are linked to the same local organization.

1. Create an org: `cognirepo org create alpha-team`
2. Link repos: `cd repo-a && cognirepo org link alpha-team .`
3. Enable cross-repo: Call MCP tools with `include_org=True`.

---

## MCP Server

CogniRepo exposes 15 MCP tools over stdio transport:

| Tool | Parameters | Returns |
|---|---|---|
| `store_memory` | `text, source` | `{status, text, importance}` |
| `retrieve_memory`| `query, top_k, include_org`| `list[{text, source_repo, ...}]` |
| `org_search` | `query, top_k` | Semantic search across the organization |
| `org_dependencies`| _(none)_ | List all linked repos in the org |
| `architecture_overview`| `scope` | High-level architectural summaries |
| `lookup_symbol` | `name, include_org` | `{file, line, type, repo}` |
| `context_pack` | `query, max_tokens` | Packed code + memory bundle |
| `who_calls` | `function_name` | List of caller locations |
| `search_docs` | `query` | Content snippets from .md files |
| `log_episode` | `event, metadata` | Record a milestone |
| `subgraph` | `entity, depth` | Graph neighbourhood |
| `explain_change` | `target, since` | Cross-reference git + memory |

---

## Memory Pruning & Circuit Breaker

### Circuit Breaker

Prevents OOM by monitoring process RSS.

```bash
export COGNIREPO_CB_RSS_LIMIT_MB=3000   # trip at 3 GB RSS
```

---

## Maintenance Commands

### `cognirepo migrate-config`

Rename deprecated tier names in `.cognirepo/config.json` to their current equivalents.
Run this once after upgrading from CogniRepo < 0.2.0; the command auto-detects any
stale tier keys and rewrites them to `STANDARD`, `COMPLEX`, or `EXPERT`.

```bash
cognirepo migrate-config           # apply changes in place
cognirepo migrate-config --dry-run # preview changes without writing
```

Safe to run on already-migrated configs.

---

## Configuration Reference

### `.cognirepo/config.json`

| Key | Type | Default | Description |
|---|---|---|---|
| `retrieval_weights.vector` | float | 0.5 | Weight for FAISS vector score |
| `retrieval_weights.graph` | float | 0.3 | Weight for graph hop score |
| `retrieval_weights.behaviour` | float | 0.2 | Weight for behaviour hit count |
| `models.STANDARD.model` | string | `gemini-2.0-flash` | Model for STANDARD tier |
| `idle_ttl_seconds` | int | `600` | Inactivity timeout for heavy resources |
| `episodic_max_events` | int | `10000` | Max episodic events before oldest 20% are rotated to `episodic_archive.json` |

## Prometheus Metrics

When `prometheus_client` is installed, CogniRepo exposes a `/metrics` endpoint via the serve API.

```bash
pip install prometheus_client
cognirepo serve
# metrics available at the /metrics path on the server port
```

The `/metrics` endpoint follows the Prometheus text exposition format.
