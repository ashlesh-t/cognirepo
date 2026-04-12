# CogniRepo

> Persistent memory and context for any AI tool. Not a chatbot — infrastructure.

[![CI](https://github.com/ashlesh-t/cognirepo/actions/workflows/ci.yml/badge.svg)](https://github.com/ashlesh-t/cognirepo/actions/workflows/ci.yml)
[![Security](https://github.com/ashlesh-t/cognirepo/actions/workflows/security.yml/badge.svg)](https://github.com/ashlesh-t/cognirepo/actions/workflows/security.yml)
[![PyPI version](https://badge.fury.io/py/cognirepo.svg)](https://badge.fury.io/py/cognirepo)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

---

## What it does

Every AI conversation starts from zero. Claude, Cursor, Gemini — none of them remember
what you fixed yesterday, which files relate to which features, or what decisions were made
last sprint. CogniRepo fixes that.

It sits between your codebase and any AI tool, providing:

- **Semantic memory** — FAISS vector store with sentence-transformer embeddings. Store
  decisions, docs, architecture notes. Retrieve them with natural language.
- **Episodic log** — append-only event journal. Know what you were doing before that error.
- **Knowledge graph** — NetworkX DiGraph of your code. Functions, classes, files, call
  relationships, concepts — all linked and queryable.
- **AST reverse index** — O(1) symbol lookup across your entire codebase in any supported language.
- **Multi-model orchestration** — classify query complexity → build context → route to the
  right model. Claude for deep reasoning, Gemini Flash for quick lookups. All automatic.

Every AI tool that connects gets the same accumulated project knowledge. Memory persists
across sessions, across tools, across time.

---

## Why it helps — measured numbers

| Metric | Value | vs. baseline |
|--------|-------|-------------|
| Token reduction per query | **98%** | vs. reading all matching source files raw |
| Symbol lookup latency | **< 1 ms** | vs. `grep` at 2–8 seconds (100 000–4 000 000× faster) |
| Cache speedup | **20 000–40 000×** | warm `hybrid_retrieve` vs. cold |
| Memory recall@3 | **100%** | stored decisions always retrievable in top-3 |
| Cost per 10-query session | **~$0.06** | vs. ~$2.40 without CogniRepo |

Run `cognirepo benchmark` on your own codebase to reproduce. See [METRICS.md](METRICS.md).

---

## How it works

```
User / AI Tool
    │
    ├── MCP stdio         (Claude Desktop, Gemini CLI, Cursor)
    ├── REST API (JWT)    (any language, any tool)
    └── gRPC              (multi-agent / inter-model)
              │
         tools/           ← single entry point to memory engine
              │
    ┌─────────┼──────────────────────┐
    ▼         ▼                      ▼
memory/    retrieval/hybrid.py    graph/
FAISS      3-signal merge:        NetworkX
episodic   vector + graph         behaviour
embeddings + behaviour            tracker
           (AST pre-scorer +
            episodic side-channel)
              │
         indexer/
         tree-sitter (Python, JS, TS, Java, Go, Rust, C++)
              │
         .cognirepo/   (Fernet encrypted if storage.encrypt: true)
```

**Two parts, one system:**

**Part A — MCP tools layer:** Eight tools exposed via MCP stdio, REST, and gRPC — store
memory, retrieve memory, search docs, log episodes, lookup symbols, get graph stats, and
more. Connect once; every AI tool sees the same accumulated context.

**Part B — CLI orchestrator:** `cognirepo ask` and `cognirepo chat` route your queries
through the multi-model orchestrator — classify complexity, build context from all memory
sources, call the best model (Claude, Gemini, Grok, OpenAI), stream the response.

---

## Quick start

### Requirements

- Python 3.11+
- At least one API key: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, or `GROK_API_KEY`

### Install

```bash
pip install cognirepo

# For multi-language indexing (JS, TS, Java, Go, Rust, C++):
pip install cognirepo[languages]

# For encryption at rest:
pip install cognirepo[security]
```

### Run

```bash
# Interactive wizard — asks about multi-model, Redis, encryption, Claude/Gemini MCP:
cognirepo init

# Non-interactive (CI / scripting):
cognirepo init --no-index --password mypass --port 8080

cognirepo index-repo .                  # index your codebase (watcher runs in foreground)
cognirepo index-repo . --daemon         # index and run watcher in background
cognirepo ask "why is auth slow?"       # route a query through the orchestrator

# Manage background watchers:
cognirepo list                          # show all running watcher daemons
cognirepo list -n <PID> --view          # tail the log of a specific watcher
cognirepo list -n <PID> --stop          # stop a watcher

# Interactive REPL:
cognirepo chat

# System health check:
cognirepo doctor
```

---

## Connect your AI tools

### Claude Code / Claude Desktop (recommended — project-scoped)

Run `cognirepo init` inside your project — it asks if you want to configure Claude and
automatically writes `.claude/CLAUDE.md` and `.claude/settings.json` with the correct
project-locked connector.

Each project gets its **own isolated connector** named `cognirepo-<project>`:

```json
{
  "mcpServers": {
    "cognirepo-myproject": {
      "command": "cognirepo",
      "args": ["serve", "--project-dir", "/abs/path/to/myproject"],
      "env": {}
    }
  }
}
```

The `--project-dir` flag locks the MCP server to that project's `.cognirepo/` directory.
When Claude has multiple projects open simultaneously, each connector reads only its own
memories, graph, and index — **never mixing data across projects or teams**.

> **Manual setup:** copy the block above into `.claude/settings.json` in your project root,
> replacing the path and project name.

CogniRepo's 9 memory tools (`retrieve_memory`, `lookup_symbol`, `search_docs`, `store_memory`,
`who_calls`, `log_episode`, `subgraph`, `graph_stats`, `episodic_search`) appear in Claude's
tool list. The `.claude/CLAUDE.md` file instructs Claude when and how to use each tool.

### Cursor / Copilot

```bash
cognirepo export-spec
cp adapters/cursor_mcp_config.json .cursor/mcp.json
# Restart Cursor — CogniRepo tools appear in the tool selector
```

### REST API (any language)

```bash
# Start the API server
cognirepo serve-api --port 8080

# Get a JWT token
TOKEN=$(curl -s -X POST http://localhost:8080/login \
  -H "Content-Type: application/json" \
  -d '{"password":"changeme"}' | jq -r .token)

# Store a memory
curl -X POST http://localhost:8080/memory/store \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "JWT tokens expire after 24h", "source": "auth-docs"}'

# Retrieve memories
curl -X POST http://localhost:8080/memory/retrieve \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "token expiry", "top_k": 5}'
```

### Docker

```bash
cp .env.example .env   # add your API keys
docker compose up api  # REST API on :8080
```

---

## Multi-model orchestration

`cognirepo ask` automatically picks the right model for each query:

| Tier | Score | Default model | Use case |
|------|-------|---------------|----------|
| **QUICK** | ≤2 | local resolver | Single-token / trivial — zero-API, fastest path |
| **STANDARD** | ≤4 | Haiku | Quick lookup, factual, single symbol |
| **COMPLEX** | ≤9 | Sonnet | Moderate reasoning |
| **EXPERT** | >9 | Opus | Cross-file, architectural, ambiguous — full context, best model |

```bash
cognirepo ask "where is verify_token defined?"       # → QUICK, answered locally
cognirepo ask "why is auth slow?"                    # → EXPERT, Claude with full context
cognirepo ask --verbose "explain the circuit breaker"  # show tier/score/signals
```

Provider fallback chain: Grok → Gemini → Anthropic → OpenAI. All errors are logged to `.cognirepo/errors/<date>.log` — no raw tracebacks shown to users. Configure tiers in `.cognirepo/config.json`.

---

## Language support

| Language | Extensions | Install |
|----------|------------|---------|
| Python | `.py` | built-in |
| JavaScript / TypeScript | `.js` `.ts` `.jsx` `.tsx` | `cognirepo[languages]` |
| Java | `.java` | `cognirepo[languages]` |
| Go | `.go` | `cognirepo[languages]` |
| Rust | `.rs` | `cognirepo[languages]` |
| C / C++ | `.c` `.cpp` `.h` | `cognirepo[languages]` |

Full details and roadmap: [LANGUAGES.md](LANGUAGES.md)

---

## Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, component responsibilities, data flow |
| [USAGE.md](USAGE.md) | Complete CLI, REST API, MCP, and Docker reference |
| [METRICS.md](METRICS.md) | Quantitative benchmarks: token reduction, lookup speedup, recall |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to add adapters, tools, and language support |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting, data handling, trust model |
| [LANGUAGES.md](LANGUAGES.md) | Language support details and roadmap |

---

## License

CogniRepo is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

**What this means:**
- ✓ Free to use, study, modify, and distribute
- ✓ Contributions and modifications must be published under AGPL v3
- ✗ You cannot offer CogniRepo as a hosted service or embed it in a closed-source
  product without open sourcing your entire stack

**Commercial licensing:**
If you need to use CogniRepo in a proprietary product or hosted service without open
sourcing your application, a commercial license is available. Contact: ashleshat5@gmail.com

See [LICENSE](LICENSE) and [NOTICE](NOTICE) for full details.
