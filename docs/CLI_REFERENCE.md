# CogniRepo CLI Reference

Complete command reference for the `cognirepo` CLI.

---

## Global Flags

| Flag | Description |
|------|-------------|
| `-h`, `--help` | Show help and exit |

---

## cognirepo init

Scaffold `.cognirepo/` and write `config.json`. Safe to re-run (idempotent).

```
cognirepo init [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--password TEXT` | `changeme` | Initial API password |
| `--port INT` | `8000` | API port to record in config |
| `--no-index` | `False` | Skip the index-repo prompt (for scripting) |
| `--daemon`, `-d` | `False` | Run file watcher as a background daemon |
| `--non-interactive` | `False` | Use all defaults without prompting (for CI) |

**Examples:**
```bash
# Interactive wizard (default)
cognirepo init

# Fully scripted setup
cognirepo init --non-interactive --no-index --password mypassword

# CI/CD usage
cognirepo init --password changeme --no-index
```

---

## cognirepo index-repo

AST-index a codebase: builds symbol index and knowledge graph.

```
cognirepo index-repo [PATH] [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `PATH` | `.` | Directory to index |
| `--no-watch` | `False` | Do not start the file watcher after indexing |
| `--daemon`, `-d` | `False` | Run the watcher as a background daemon |

**Examples:**
```bash
cognirepo index-repo .
cognirepo index-repo /path/to/repo --no-watch
cognirepo index-repo . --daemon
```

---

## cognirepo serve

Start the MCP stdio server (for Claude Desktop, Gemini CLI, Cursor).

```
cognirepo serve [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--project-dir DIR` | `.` | Project root to serve |

**Examples:**
```bash
cognirepo serve
cognirepo serve --project-dir /path/to/project
```

---



```
```

| Flag | Default | Description |
|------|---------|-------------|
| `--host TEXT` | `0.0.0.0` | Host to bind |
| `--port INT` | `8000` | Port to bind |
| `--reload` | `False` | Enable hot reload (development mode) |

**Examples:**
```bash
```

---



```
```

| Flag | Default | Description |
|------|---------|-------------|
| `--idle-timeout INT` | `300` | Seconds of inactivity before auto-shutdown |

---

## cognirepo watch

Start or manage the file watcher.

```
cognirepo watch [PATH] [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `PATH` | `.` | Directory to watch |
| `--daemon`, `-d` | `False` | Run in background |
| `--ensure-running` | `False` | Start if not running or heartbeat stale |

**Examples:**
```bash
cognirepo watch .
cognirepo watch . --daemon
cognirepo watch --ensure-running .
```

---

## cognirepo store-memory

Save a semantic memory to the FAISS index.

```
cognirepo store-memory TEXT [OPTIONS]
```

| Arg | Description |
|-----|-------------|
| `TEXT` | Memory text to store |
| `--source TEXT` | Source label (e.g., "debug", "decision") |

**Examples:**
```bash
cognirepo store-memory "Fixed: cache_get was not JSON-decoding values" --source debug
cognirepo store-memory "Architecture: tools/ is the single source of truth"
```

---

## cognirepo retrieve-memory

Similarity search over stored memories.

```
cognirepo retrieve-memory QUERY [OPTIONS]
```

| Arg | Description |
|-----|-------------|
| `QUERY` | Natural language search query |
| `--top-k INT` | Number of results (default: 5) |

**Examples:**
```bash
cognirepo retrieve-memory "how we fixed the BM25 bug"
cognirepo retrieve-memory "redis connection issues" --top-k 3
```

---

## cognirepo search-docs

Full-text search over all `.md` documentation.

```
cognirepo search-docs QUERY
```

**Examples:**
```bash
cognirepo search-docs "how to add a language"
cognirepo search-docs "JWT authentication"
```

---

## cognirepo doctor

Check CogniRepo installation health.

```
cognirepo doctor [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--verbose`, `-v` | `False` | Show optional component checks |

**Examples:**
```bash
cognirepo doctor
cognirepo doctor --verbose
```

**Exit codes:**
- `0` — No issues found
- `N` — N issues found

---

## cognirepo prune

Remove low-importance or stale memories.

```
cognirepo prune [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--threshold FLOAT` | `0.3` | Importance threshold below which to prune |
| `--dry-run` | `False` | Show what would be pruned without removing |
| `--archive` | `False` | Archive pruned entries instead of deleting |
| `--aggressive` | `False` | Use a lower threshold for aggressive pruning |
| `--verbose`, `-v` | `False` | Show what is being pruned |

**Examples:**
```bash
cognirepo prune --dry-run
cognirepo prune --threshold 0.4 --verbose
```

---

## cognirepo history

Show recent episodic events.

```
cognirepo history [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--limit INT` | `10` | Number of events to show |

---

## cognirepo log-episode

Record a milestone or event.

```
cognirepo log-episode EVENT
```

**Examples:**
```bash
cognirepo log-episode "Completed Sprint 5 — Redis caching integrated"
```

---

## cognirepo list

List or inspect running cognirepo daemons.

```
cognirepo list [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `-p`, `--processes` | `False` | List all running watcher processes |
| `-n`, `--name PID_OR_NAME` | — | Select a daemon by PID or name |
| `--view` | `False` | Tail the log of a selected daemon |
| `--stop` | `False` | Send SIGTERM to a selected daemon |

---

## cognirepo wait-api

Wait until the REST API is ready.

```
cognirepo wait-api [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--api-url URL` | from config | API URL to poll |
| `--timeout INT` | `60` | Seconds to wait |
| `--interval FLOAT` | `1.0` | Poll interval in seconds |

**Examples:**
```bash
cognirepo wait-api --timeout 30
```

---

## cognirepo export-spec

Export the OpenAI-compatible tool spec as JSON (for tool registration).

```
cognirepo export-spec
```
