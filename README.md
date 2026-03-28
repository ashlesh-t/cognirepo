# CogniRepo

> Persistent memory and context for any AI tool. Not a chatbot — infrastructure.

[![CI](https://github.com/ashlesh-t/cognirepo/actions/workflows/ci.yml/badge.svg)](https://github.com/ashlesh-t/cognirepo/actions/workflows/ci.yml)
[![Security](https://github.com/ashlesh-t/cognirepo/actions/workflows/security.yml/badge.svg)](https://github.com/ashlesh-t/cognirepo/actions/workflows/security.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

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
FAISS      4-signal merge:        NetworkX
episodic   vector + graph         behaviour
embeddings + AST + episodic       tracker
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
cognirepo init                          # scaffold .cognirepo/ and config
cognirepo index-repo .                  # index your codebase
cognirepo ask "why is auth slow?"       # route a query through the orchestrator

# Interactive REPL:
cognirepo chat

# System health check:
cognirepo doctor
```

---

## Connect your AI tools

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cognirepo": {
      "command": "cognirepo",
      "args": ["serve"]
    }
  }
}
```

CogniRepo's 8 memory tools appear automatically in Claude's tool list. Every conversation
now has access to your project's semantic memory, code structure, and event history.

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

| Tier | Score | Use case |
|------|-------|----------|
| FAST | 0–6 | Quick lookup, factual, single symbol — answered from local index when possible |
| BALANCED | 7–14 | Moderate reasoning |
| DEEP | 15+ | Cross-file, architectural, ambiguous — full context, best model |

```bash
cognirepo ask "where is verify_token defined?"       # → FAST, answered locally
cognirepo ask "why is auth slow?"                    # → DEEP, Claude with full context
cognirepo ask --verbose "explain the circuit breaker"  # show tier/score/signals
```

Provider fallback chain: Anthropic → Gemini → Grok → OpenAI. Configure in `.cognirepo/config.json`.

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
