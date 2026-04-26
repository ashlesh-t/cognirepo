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
8. [Cursor Integration](#cursor-integration)
9. [VS Code MCP Setup](#vs-code-mcp-setup)
10. [GitHub Copilot Integration](#github-copilot-integration)
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

CogniRepo exposes 28 MCP tools over stdio transport:

| Tool | Parameters | Returns |
|---|---|---|
| `store_memory` | `text, source` | `{status, text, importance}` |
| `retrieve_memory`| `query, top_k, include_org`| `list[{text, source_repo, ...}]` |
| `org_search` | `query, top_k` | Semantic search across the organization |
| `org_dependencies`| _(none)_ | List all linked repos in the org |
| `architecture_overview`| `scope` | High-level architectural summaries |
| `lookup_symbol` | `name, include_org` | `{file, line, type, repo}` |
| `context_pack` | `query, max_tokens` | Packed code + memory bundle (≤ 2000 tokens by default) |
| `who_calls` | `function_name` | List of caller locations |
| `search_docs` | `query, top_k` | Content snippets from .md/.rst files |
| `log_episode` | `event, metadata` | Record a milestone or event |
| `record_decision` | `summary, rationale` | Record an architectural decision |
| `subgraph` | `entity, depth` | Graph neighbourhood |
| `explain_change` | `target, since` | Cross-reference git + memory |

> **`context_pack` token limit:** Returns at most `max_tokens` tokens (default: 2000).
> This is intentionally bounded — much smaller than reading the full file.
> The cross-agent handoff snapshot (`last_context.json`) captures **only** the most recent
> `context_pack` result — it is NOT a full session transcript.
> For full session history, use `episodic_search()`.

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
Run this once after upgrading from CogniRepo < 0.3.0; the command auto-detects any
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

When `prometheus-client` is installed (**dev dependency only**, not included in base install),
CogniRepo tracks internal counters via `server/metrics.py`. These counters are in-process only.

```bash
pip install prometheus-client   # dev only
cognirepo serve
```

**Note:** A `/metrics` HTTP endpoint is NOT exposed by `cognirepo serve`. The counters are
internal and available programmatically via `server.metrics`. To scrape them you must instrument
the FastMCP server yourself or use a push-gateway pattern.

---

## Cursor Integration

Cursor reads tool routing rules from `.cursor/rules/*.mdc`. CogniRepo ships a rules file that
makes Cursor use CogniRepo tools before native file exploration.

### Setup

1. Start the MCP server (add to Cursor MCP settings):

```json
{
  "cognirepo": {
    "command": "cognirepo",
    "args": ["serve", "--project-dir", "/abs/path/to/project"],
    "type": "stdio"
  }
}
```

2. The `.cursor/rules/cognirepo.mdc` file is already in the repo. Cursor picks it up automatically.

### Session start sequence (Cursor)

Cursor agent calls these at session start:

1. `get_session_brief` — architecture summary, hot symbols, index health
2. `get_last_context` — resume where previous agent left off

> **Handoff limitation:** `get_last_context()` returns the most recent `context_pack` snapshot
> only — not a full session transcript. Use `episodic_search()` for full session history.

### `cognirepo setup` auto-configures Cursor

If `.cursor/` exists in the project root, `cognirepo setup` writes `.cursor/rules/cognirepo.mdc`
automatically.

---

## VS Code MCP Setup

VS Code supports MCP servers via `.vscode/mcp.json`.

### Quick setup

Copy the example config:

```bash
cp .vscode/mcp.json.example .vscode/mcp.json
```

Or create `.vscode/mcp.json` manually:

```json
{
  "servers": {
    "cognirepo": {
      "type": "stdio",
      "command": "cognirepo",
      "args": ["serve", "--project-dir", "${workspaceFolder}"]
    }
  }
}
```

`${workspaceFolder}` resolves to the open workspace root automatically.

### Requirements

- VS Code with MCP extension support (GitHub Copilot Chat or compatible extension)
- CogniRepo installed: `pip install 'cognirepo[cpu,languages]'`
- Repo indexed: `cognirepo index-repo .`

### `cognirepo setup` auto-configures VS Code

`cognirepo setup` detects VS Code and prints the MCP config path. Copy or symlink
`.vscode/mcp.json.example` → `.vscode/mcp.json` to activate.

---

## GitHub Copilot Integration

GitHub Copilot Chat in VS Code supports MCP tools when configured via `.vscode/mcp.json`.

### Setup

1. Install [GitHub Copilot](https://marketplace.visualstudio.com/items?itemName=GitHub.copilot) and
   [GitHub Copilot Chat](https://marketplace.visualstudio.com/items?itemName=GitHub.copilot-chat)
2. Configure `.vscode/mcp.json` (see [VS Code MCP Setup](#vs-code-mcp-setup) above)
3. Run `cognirepo index-repo .` so the index is populated
4. Open Copilot Chat — CogniRepo tools appear as available context sources

### Usage

In Copilot Chat, CogniRepo tools activate automatically when Copilot needs code context.
You can also invoke them explicitly:

```
@cognirepo context_pack("authentication flow")
@cognirepo lookup_symbol("hybrid_retrieve")
```

### Adding API Keys

Set keys as environment variables before running `cognirepo serve`:

```bash
export ANTHROPIC_API_KEY=sk-ant-...      # Claude (required for COMPLEX/EXPERT tier)
export GEMINI_API_KEY=AIza...            # Gemini (required for STANDARD tier)
export OPENAI_API_KEY=sk-...             # OpenAI (optional alternative)
```

Or add to `.env` (never commit this file):

```bash
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...
```

MCP tools and `cognirepo ask` work without any API keys — local QUICK-tier resolution only.
API keys are only needed if you use `cognirepo ask` with STANDARD/COMPLEX/EXPERT tier routing
via the `[providers]` extra.
