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
| `--daemon`, `-d` | `False` | Run the watcher as a background daemon |
| `--changed-only` | `False` | Auto-detect changed files via git and reindex |

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

---

## cognirepo user-prefs

View or set global user preferences stored in `~/.cognirepo/`.

```bash
cognirepo user-prefs [KEY [VALUE]]
```
