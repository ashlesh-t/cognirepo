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
