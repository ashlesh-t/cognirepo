# CogniRepo CLI Reference

Complete command reference for the `cognirepo` CLI.

> **REPL slash commands** (e.g. `/help`, `/model`, `/clear`) are documented in [docs/CLI.md](CLI.md).

---

## Global Flags

| Flag | Description |
|------|-------------|
| `-h`, `--help` | Show help and exit |

---

## cognirepo init

Scaffold `.cognirepo/` and write `config.json`. Safe to re-run (idempotent).

```bash
cognirepo init [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--no-index` | `False` | Skip the index-repo prompt (for scripting) |
| `--daemon`, `-d` | `False` | Run file watcher as a background daemon |
| `--non-interactive` | `False` | Use all defaults without prompting (for CI) |

---

## cognirepo index-repo

AST-index a codebase: builds symbol index and knowledge graph.

```bash
cognirepo index-repo [PATH] [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `PATH` | `.` | Directory to index |
| `--no-watch` | `False` | Do not start the file watcher after indexing |
| `--daemon`, `-d` | `False` | Run the watcher as a background daemon: a fresh detached `watch --foreground` process (~100 MB), not a fork of this one, so it does not carry the indexing run's embedder/FAISS/AST heap |
| `--no-embed` | `False` | Skip FAISS embedding (AST/symbol index + graph only). The post-commit hook passes it so a commit never loads the embedding model; vectors for those files catch up on the next full index |
| `--files FILE…` | — | Re-index only these files (used by the post-commit hook). Persists the graph **and** the AST index, FAISS vectors and manifest, so `lookup_symbol` sees the change from any process (COGNIREPO-154). Same complete-graph guard as `--changed-only` |
| `--changed-only` | `False` | Auto-detect changed files via git and reindex. Like `--files` it only updates an existing **complete** graph: if the graph is missing, quarantined or a fragment it exits `2` without saving and tells you to run a full `cognirepo index-repo .` once (COGNIREPO-122). File extensions come from `language_registry` (installed grammars). If git cannot list changes (not a repo, no commits, git missing) it exits `1` and indexes nothing (COGNIREPO-155) |

`cognirepo install-hooks` writes a post-commit hook that runs `index-repo --files <changed> --no-watch --no-embed`. Its extension filter is generated from `language_registry` (every mapped extension), The hook logs to `.cognirepo/hook.log` (rotated at 256 KiB) and records its last outcome in `.cognirepo/hook.last` (`ts`/`exit`/`files`); `doctor` and `get_session_brief` report a failed run. Re-run `install-hooks` after upgrading — it replaces an outdated cognirepo block in place and leaves your own hook lines alone.

---

## cognirepo summarize

Generate hierarchical architectural summaries via LLM.

```bash
cognirepo summarize
```

---

## cognirepo org

Manage local repository organizations (cross-repo context).

```bash
cognirepo org [create|list|link|unlink] [ARGS]
```

**Examples:**
```bash
cognirepo org create my-team
cognirepo org link my-team .
cognirepo org list
```

---

## cognirepo serve

Start the MCP stdio server (for Claude Desktop, Gemini CLI, Cursor).

```bash
cognirepo serve [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--project-dir DIR` | `None` | Project root to serve (locks server to this project) |

---

## cognirepo doctor

Check CogniRepo installation health.

```bash
cognirepo doctor [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--verbose`, `-v` | `False` | Show optional component checks |
| `--fix` | `False` | Auto-fix FAISS corruption or dimension mismatch |

`doctor` also probes the interpreter behind the `cognirepo` on `PATH` (read-only, in a subprocess): with
`storage.encrypt: true` it reports missing `keyring`/`cryptography` or an unusable keyring backend there,
and it warns when that install is a stale copy of the current working tree, printing the exact
`pipx inject` / `pipx install --force` command.

---

## cognirepo store-memory

Save a semantic memory to the FAISS index.

```bash
cognirepo store-memory TEXT [OPTIONS]
```

| Arg | Description |
|-----|-------------|
| `TEXT` | Memory text to store |
| `--source TEXT` | Source label (e.g., "debug", "decision") |
| `--global` | Save to the global user store (~/.cognirepo/) |

---

## cognirepo retrieve-memory

Similarity search over stored memories.

```bash
cognirepo retrieve-memory QUERY [OPTIONS]
```

| Arg | Description |
|-----|-------------|
| `QUERY` | Natural language search query |
| `--top-k INT` | Number of results (default: 5) |
| `--global` | Search the global user store |

---

## cognirepo status

Show live retrieval signal weights and index health.

```bash
cognirepo status
```

---

## cognirepo prime

Generate a session brief for agent bootstrap (architecture, entry points, hot symbols).

```bash
cognirepo prime [--json]
```

---

## cognirepo insights

Generate/update the repo insights HTML report — timeline, decisions, challenges (recurring errors), branch/commit activity, index health. Sourced only from real stored records; re-running updates the same file in place at `.claude/insights/<repoName>-insights.html` (markdown twin under `.cognirepo/docs/`, searchable via `search-docs`).

```bash
cognirepo insights [--since 90d]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--since` | `90d` | History window |

---

## cognirepo prune

Remove low-importance or stale memories.

```bash
cognirepo prune [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | `False` | Show what would be pruned without removing |
| `--archive` | `False` | Archive pruned entries instead of deleting |
| `--aggressive` | `False` | Use a lower threshold (0.05) |

---

## cognirepo setup

One-command onboarding: `init` + `index-repo` + MCP config generation. Installs optional extras (languages, security, providers) interactively.

```bash
cognirepo setup
```

Detects `.cursor/`, `.vscode/`, and `.claude/` and writes the appropriate MCP connector config for each.

---

## cognirepo migrate-config

Migrate `config.json` from legacy tier names (`FAST/BALANCED/DEEP`) to current names (`STANDARD/COMPLEX/EXPERT`).

```bash
cognirepo migrate-config           # apply in place
cognirepo migrate-config --dry-run # preview changes without writing
```

---

## cognirepo ask

Send a single query through the full orchestrator pipeline (classifier → context builder → model router) without entering the REPL.

```bash
cognirepo ask "QUERY" [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--model MODEL` | tier default | Override model for this query |
| `--tier TIER` | auto-classified | Force a specific tier (QUICK/STANDARD/COMPLEX/EXPERT) |

---

## cognirepo benchmark

Run quantitative value benchmarks and report token-reduction metrics.

```bash
cognirepo benchmark [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--json` | `False` | Output results as JSON |

---

## cognirepo search-docs

Full-text search over `.md` files in the project.

```bash
cognirepo search-docs QUERY
```

---

## cognirepo log-episode

Append an episodic event to the journal.

```bash
cognirepo log-episode TEXT
```

---

## cognirepo history

Print recent episodic events.

```bash
cognirepo history [--limit N]
```

---

## cognirepo seed

Seed the behaviour tracker and learning store from git log.

```bash
cognirepo seed [--days N]
```

---

## cognirepo sessions

List recent conversation sessions.

```bash
cognirepo sessions
```

---

## cognirepo watch

Manage the background file-watcher daemon.

```bash
cognirepo watch start|stop|status
```

**One watcher per repo (COGNIREPO-138).** However many processes try to start a watcher — `watch --daemon`,
`watch --foreground`, `watch --ensure-running`, or the watcher thread every `cognirepo serve` session
starts — exactly one runs. The process that actually runs the observer holds a per-repo lease (an OS file
lock on `.cognirepo/watchers/watcher.writer`, owner pid in `watcher.writer.pid`); the kernel drops it when
that process exits or is killed. Only the holder loads the graph/index, registers itself in
`.cognirepo/watchers/<pid>.json` and writes the heartbeat. Other `serve` sessions stand by (nothing loaded,
re-check every 15 s) and take over if the holder dies; other CLI starters print who holds it and exit.
A watcher that is the thread inside a `serve` session shows as `running (in serve)` in `cognirepo list`
and `list --stop` refuses to signal it (that would stop the agent's server) — it ends with that session.

---

## cognirepo user-prefs

View or set global user preferences stored in `~/.cognirepo/`.

```bash
cognirepo user-prefs [KEY [VALUE]]
```

---

## cognirepo episodic-search

Keyword search in episodic event history.

```bash
cognirepo episodic-search QUERY [OPTIONS]
```

| Arg / Flag | Default | Description |
|------|---------|-------------|
| `QUERY` | — | Search term to match against episodic events |
| `--limit INT` | `10` | Max results to return |

---

## cognirepo lookup-symbol

Find where a function or class is defined.

```bash
cognirepo lookup-symbol NAME [OPTIONS]
```

| Arg / Flag | Default | Description |
|------|---------|-------------|
| `NAME` | — | Symbol name to look up |
| `--include-org` | `False` | Also search sibling repos in the same organization |

---

## cognirepo who-calls

Trace callers of a function in the call graph.

```bash
cognirepo who-calls FUNCTION
```

| Arg | Description |
|-----|-------------|
| `FUNCTION` | Function name to trace callers of |

---

## cognirepo subgraph

Print the knowledge-graph neighbourhood around an entity.

```bash
cognirepo subgraph ENTITY [OPTIONS]
```

| Arg / Flag | Default | Description |
|------|---------|-------------|
| `ENTITY` | — | Node ID (file, function, class, …) to center the subgraph on |
| `--depth INT` | `2` | Hop distance to traverse from the entity |

---

## cognirepo graph

Knowledge-graph integrity maintenance. Has one subcommand, `repair`.

```bash
cognirepo graph repair [--apply]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--apply` | `False` | Actually prune dangling file nodes **and orphan `symbol::<name>` stubs** — degree-0 leftovers of deleted symbols (default: dry-run report only) |

---

## cognirepo mcp-setup

Re-run MCP integration for Claude Code / Gemini CLI / Cursor / VS Code without repeating the full `cognirepo init` wizard.

```bash
cognirepo mcp-setup [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--target {claude,gemini,cursor,vscode}` | `claude` | Repeatable — pass multiple times to configure more than one target |
| `--global` | `False` | Also register the server user-wide, not just this project |

---

## cognirepo verify-index

Verify that the AST index is fresh and untampered, by checking file hashes against `manifest.json`.

```bash
cognirepo verify-index [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--verbose`, `-v` | `False` | List all dirty indexed files, not just the first 5 |

---

## cognirepo index-progress

Live terminal view of background indexing and Tier-2 FAISS embedding progress.

```bash
cognirepo index-progress [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--interval SECS` | `1.0` | Refresh interval in seconds |
| `--once` | `False` | Print once and exit instead of refreshing continuously |

---

## cognirepo test-connection

Verify an API key and connectivity for a model provider.

```bash
cognirepo test-connection [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--provider {anthropic,gemini,grok,openai}` | none (tests all configured) | Provider to test; omit to test every configured provider |

---

## cognirepo setup-env

Interactive wizard to set and verify model-provider API keys.

```bash
cognirepo setup-env [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--skip-verify` | `False` | Write keys but skip the API verification call (useful in CI with real keys) |
| `--non-interactive` | `False` | Skip the wizard entirely (for scripted environments) |

---

## cognirepo metrics

Serve Prometheus `/metrics` on a standalone HTTP port — for MCP-only deployments where the MCP server process itself isn't reachable over HTTP.

```bash
cognirepo metrics [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--host HOST` | `127.0.0.1` | Bind host |
| `--port PORT` | `9090` | Port to listen on |

---

## cognirepo list

List MCP servers, organizations, and running watcher daemons.

```bash
cognirepo list [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `-p`, `--processes` | `False` | List all running watcher daemon processes |
| `-n`, `--name PID_OR_NAME` | `None` | Select a daemon by PID or name (use with `--view` or `--stop`) |
| `--view` | `False` | Interactively tail the log of the daemon selected with `-n` |
| `--stop` | `False` | Stop the daemon selected with `-n`: sends SIGTERM and **waits** for the process to exit (up to 30 s), then SIGKILLs it; the registration is cleared only once the process is really gone. Exit 1 if it could not be stopped, or if the target is a watcher thread embedded in a `serve` session (nothing is signalled) |
| `--org` | `False` | Show all organizations, repos, and projects from `orgs.json` |
| `--mcp` | `False` | List registered MCP servers from `.mcp.json` and global configs |

---

## cognirepo delete

Remove CogniRepo data: a project's local `.cognirepo/`, org entries, or global state.

```bash
cognirepo delete [PROJECT_NAME] [OPTIONS]
```

| Arg / Flag | Default | Description |
|------|---------|-------------|
| `PROJECT_NAME` | `None` | Delete shared memory for the named project and unlink all its repos |
| `--org ORG_NAME` | `None` | Delete an org plus all its projects and all shared memory paths |
| `--all` | `False` | Delete ALL CogniRepo traces system-wide (irreversible) |
| `-y`, `--yes` | `False` | Skip the confirmation prompt |
