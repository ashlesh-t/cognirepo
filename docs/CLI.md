# CogniRepo CLI Reference

Full reference for the `cognirepo` interactive REPL and all slash commands.

---

## Starting the REPL

```bash
cognirepo                          # start interactive REPL
cognirepo --model claude-opus-4-6  # force a specific model for all queries
```

On startup the REPL shows:
- Project name and memory/graph counts
- Current multi-agent status
- Type `/help` for all commands

---

## Slash Commands

| Command | Syntax | Description |
|---|---|---|
| `/help` | `/help` | List all available slash commands |
| `/clear` | `/clear` | Clear conversation history for this session |
| `/exit` | `/exit` | Exit the REPL (also: `Ctrl+D`, `quit`) |
| `/status` | `/status` | Show FAISS size, graph stats, circuit breaker, sub-agents |
| `/memories` | `/memories` | Show the 5 most recent stored memories |
| `/graph` | `/graph` | Show knowledge graph node/edge count |
| `/history` | `/history` | Show conversation history for this session |
| `/model` | `/model` | Show current tier/model |
| `/model set <id>` | `/model set claude-opus-4-6` | Override model for all subsequent queries |
| `/save` | `/save [name]` | Save current session to disk |
| `/load` | `/load <id-prefix\|last>` | Load a saved session |
| `/index-repo` | `/index-repo` | Re-index the current repository (AST + knowledge graph) |
| `/agents` | `/agents` | List all sub-agent sessions for the current turn |
| `/agents cancel <id>` | `/agents cancel abc123` | Cancel a pending/running sub-agent |

---

## Query Tiers

Every query is automatically classified into a tier:

| Tier | Score | Provider | Model | Use case |
|---|---|---|---|---|
| **QUICK** | ≤ 2 | local | local-resolver | Docs lookups, symbol finds — zero-API |
| **STANDARD** | ≤ 4 | anthropic | claude-haiku-4-5 | Factual, single-entity |
| **COMPLEX** | ≤ 9 | anthropic | claude-sonnet-4-6 | Moderate reasoning |
| **EXPERT** | > 9 | anthropic | claude-opus-4-6 | Cross-file, architectural |

Override for one query: `/model set <model-id>` before asking.

---

## QUICK-tier local resolution

QUICK-tier queries are answered without any API call:

1. **Pattern matcher** — `try_local_resolve()` handles: `lookup_symbol`, `who_calls`, `list_files`, `graph_stats`, history queries
2. **Docs index** — FAISS-indexed CogniRepo `.md` files answer "how do I…" questions

If neither source has a confident answer (score < 0.6), the query is promoted to STANDARD.

---

## Session persistence

Configure in `~/.cognirepo/cli_config.toml`:

```toml
[session]
persist = true        # auto-save every exchange (default: true)
max_exchanges = 20    # keep last N exchanges in session file
```

- `/save [name]` — save with an optional name hint
- `/load last` — restore the most recent session
- `/load <prefix>` — restore by session ID prefix (e.g. `/load a3f`)

Session files live in `.cognirepo/sessions/`.

---

## Multi-agent mode


```bash

# Terminal 2 — start the REPL with multi-agent enabled
```

For **EXPERT**-tier queries, the REPL:
2. Shows a greyed-out sub-agent panel after the primary response
3. Stores sub-query results in the session JSON under `sub_queries[]`

Use `/agents` to inspect sub-agent state and `/agents cancel <id>` to stop one.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `COGNIREPO_LOG_LEVEL` | `WARNING` | Log level (DEBUG/INFO/WARNING/ERROR) |
| `COGNIREPO_LOG_FORMAT` | `json` in non-tty, `text` in tty | Log format |
| `ANTHROPIC_API_KEY` | — | Claude API key |
| `GEMINI_API_KEY` | — | Gemini API key |
| `GROK_API_KEY` | — | Grok / xAI API key |
| `OPENAI_API_KEY` | — | OpenAI API key |

---

## CLI config file

Location: `~/.cognirepo/cli_config.toml`

```toml
[ui]
color = true
show_tier_label = true

[model]
prefer = ""           # e.g. "claude-opus-4-6" to always use this model

[session]
persist = true
max_exchanges = 20
```

---

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Ctrl+C` | Cancel current input (double-tap to force quit) |
| `Ctrl+D` | Exit the REPL |
| `↑` / `↓` | Navigate input history (when prompt_toolkit is installed) |
| `Tab` | Auto-complete slash commands |
