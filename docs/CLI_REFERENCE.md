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
| `--no-graph` | `False` | Disable knowledge-graph building entirely. For repos over 10k files a lightweight graph (entry-point symbols only) is built automatically; this skips it |
| `--parent-repo PATH` | — | Link this repo as a child of the given parent repo in the org graph (microservices; see below) |
| `--no-link` | `False` | Skip org-graph linking (standalone repo, no parent) |
| `--service-type TYPE` | — | Microservice type: `rest_api` \| `grpc` \| `worker` \| `frontend` \| `library` \| `other` |
| `--port PORT` | — | Port the service listens on (stored in the org-graph metadata) |
| `--api-base-url URL` | — | Base URL or path prefix of the service's API, e.g. `/api/v1` (stored in the org-graph metadata) |

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
| `--no-graph` | `False` | Disable knowledge-graph building entirely (for very large repos). Repos over 10k files get a lightweight graph by default |
| `--tier {1,2,all}` | auto | `1`: high-weight files only (fast bootstrap, the rest is queued); `2`: resume the queued background pass; `all`: full index regardless of size |
| `--remove-lock LOCK_PATH` | — | Delete the file at `LOCK_PATH` after indexing (used by the background reindex to release its lock) |

`cognirepo install-hooks` writes a post-commit hook that runs `index-repo --files <changed> --no-watch --no-embed`. Its extension filter is generated from `language_registry` (every mapped extension). The hook logs to `.cognirepo/hook.log` (rotated at 256 KiB) and records its last outcome in `.cognirepo/hook.last` (`ts`/`exit`/`files`); `doctor` and `get_session_brief` report a failed run. Re-run `install-hooks` after upgrading — it replaces an outdated cognirepo block in place and leaves your own hook lines alone.

---

## cognirepo summarize


Generate hierarchical architectural summaries via LLM.

```bash
cognirepo summarize [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--scope DIR` | whole repo | Restrict summarization to files under this directory prefix (e.g. `pkg/`) |
| `--embed-only` | `False` | Skip text summarization; only embed the existing `summaries.json` into FAISS. Used automatically by the background pass for large repos |

---

## cognirepo org


Manage local repository organizations (cross-repo context) and the org dependency graph.

```bash
cognirepo org create NAME
cognirepo org list
cognirepo org link ORG [PATH]
cognirepo org unlink ORG [PATH]
cognirepo org link-repos REPO_A REPO_B [--type IMPORTS|CALLS_API|SHARES_SCHEMA]
cognirepo org graph [--json]
cognirepo org rewire
cognirepo org project create ORG PROJECT [--description TEXT]
cognirepo org project list ORG
cognirepo org project link ORG PROJECT [PATH]
cognirepo org project unlink ORG PROJECT [PATH]
```

| Subcommand | Description |
|------------|-------------|
| `create NAME` | Create a new local organization |
| `list` | List all local organizations and their member repos |
| `link ORG [PATH]` / `unlink ORG [PATH]` | Add / remove a repo (default: the current directory) |
| `link-repos REPO_A REPO_B` | Declare a dependency edge: `REPO_A` depends on `REPO_B`. `--type` is the edge kind (`IMPORTS` default, `CALLS_API`, `SHARES_SCHEMA`) |
| `graph` | Print the org dependency graph; `--json` for machine-readable output |
| `rewire` | Re-run cross-service `CALLS_API` detection for every indexed repo (run it after indexing all services) |
| `project …` | Manage projects within an organization: `create` (with `--description`), `list`, `link`, `unlink` |

**Examples:**
```bash
cognirepo org create my-team
cognirepo org link my-team .
cognirepo org list
cognirepo org link-repos ./api ./auth --type CALLS_API
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
| `--release-check` | `False` | Also run release-readiness checks (v0.x references, old tier names in docs) |
| `--json` | `False` | Output the diagnostics as JSON (machine-readable); combine with `--resources` for the resource report |
| `--resources` | `False` | Instead of the health checks, print where memory and disk go: every cognirepo process (resident memory, age, repo, stale flag), the size of each `.cognirepo/` subdirectory with its largest files, and set-aside/left-over files (quarantines, `.stale`, scratch). Read-only; add `--json` for scripts. See [RESOURCES.md](RESOURCES.md) |

`doctor` warns about **stale cognirepo processes** (Linux): a watcher/indexer whose working directory was deleted, or a one-shot command (`init`, `index-repo`, …) still running after 6 h, with their combined memory and the `kill` command. Agent `serve` sessions are never reported.

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
| `--threshold FLOAT` | `0.15` | Prune memories whose score (importance × recency decay) is below this value. `--aggressive` is the same as `--threshold 0.05` |
| `--verbose` | `False` | List every memory considered (implied by `--dry-run`) |

---

## cognirepo setup


One-command onboarding: `init` + `index-repo` + MCP config generation. Installs optional extras (languages, security, providers) interactively.

```bash
cognirepo setup [--no-index] [--targets claude cursor vscode]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--no-index` | `False` | Skip indexing (scaffold `.cognirepo/` only) |
| `--targets …` | auto-detected | MCP targets to configure: `claude`, `cursor`, `vscode` |

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
| `QUERY` | — | Natural-language query (optional; omitted, it reads from the prompt) |
| `--verbose`, `-v` | `False` | Show the classifier tier and the matched source |
| `--top-k N` | `5` | Number of symbols to retrieve for context |

---

## cognirepo benchmark


Run quantitative value benchmarks and report token-reduction metrics.

```bash
cognirepo benchmark [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--json` | `False` | Output raw JSON instead of the report |
| `--compare` | `False` | Compare with the previous run |

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
cognirepo log-episode EVENT [--meta JSON]
```

| Flag | Default | Description |
|------|---------|-------------|
| `EVENT` | — | The event text |
| `--meta JSON` | `{}` | JSON metadata object stored with the event |

---

## cognirepo history


Print recent episodic events.

```bash
cognirepo history [--limit N]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--limit N` | `20` | Number of events to show |

---

## cognirepo seed


Seed the behaviour tracker and learning store from git history.

```bash
cognirepo seed [--path DIR] [--dry-run] [--from-git] [--comments]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--path DIR` | `.` | Repo root to read git history from |
| `--dry-run` | `False` | Show which files/symbols would be seeded without writing anything |
| `--from-git` | `False` | Also parse commit messages (`fix:` / `decision:` / `breaking:`) and ADR files into the learning store |
| `--comments` | `False` | Also scan source files for `FIXME` / `HACK` / `NOTE` comments (slow on large repos) |

---

## cognirepo sessions


List recent conversation sessions.

```bash
cognirepo sessions [--limit N]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--limit N` | `20` | Maximum number of sessions to show |

---

## cognirepo watch


Manage the background file-watcher. There are no `start` / `stop` / `status` subcommands: starting is `--ensure-running` (or `--foreground` under a supervisor), status is `--status`, and stopping is `cognirepo list -n <PID_OR_NAME> --stop` (see [`list`](#cognirepo-list)).

```bash
cognirepo watch [--status | --ensure-running | --foreground] [--path DIR]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--status` | `False` | Print daemon status: PID, heartbeat age, last reindex |
| `--ensure-running` | `False` | Start the watcher (a fresh background process) if it is not running or its heartbeat is stale (> 60 s) |
| `--foreground`, `--daemon-foreground` | `False` | Run the watcher in the foreground under the crash guard — what the generated systemd/launchd unit runs. Registers itself, logs to stderr, stops cleanly on SIGTERM. `--daemon-foreground` is the name older generated units use |
| `--path DIR` | `.` | Repo root to watch |

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
cognirepo user-prefs                    # show preferences
cognirepo user-prefs --set KEY VALUE    # set one
cognirepo user-prefs --behaviour        # show auto-tracked behaviour pattern counts
```

| Flag | Default | Description |
|------|---------|-------------|
| `--set KEY VALUE` | — | Set a preference |
| `--behaviour` | `False` | Show auto-tracked behaviour pattern counts |

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

Knowledge-graph integrity maintenance: `repair`, `restore` and `prune-quarantine`. All three are dry-run unless `--apply` is given.

```bash
cognirepo graph repair [--apply]
cognirepo graph restore [--apply] [--force]
cognirepo graph prune-quarantine [--days N] [--apply]
```

| Command / flag | Default | Description |
|------|---------|-------------|
| `repair --apply` | `False` | Actually prune dangling file nodes **and orphan `symbol::<name>` stubs** — degree-0 leftovers of deleted symbols (default: dry-run report only) |
| `restore` | — | Lists every `graph.pkl.corrupt-<ts>` file, inspecting each with the **current key**: `recoverable` (decrypts/unpickles to a graph, shows nodes/edges), `locked` (still ciphertext this interpreter cannot decrypt) or `corrupt`. Then restores the **largest** recoverable one as `graph.pkl` (not the newest: a later quarantine is usually a tiny graph that replaced a big one) |
| `restore --apply` | `False` | Do it. The quarantined file is **copied**, never moved or deleted |
| `restore --force` | `False` | Also replace a `graph.pkl` that is itself readable (kept as `graph.pkl.replaced-<ts>`). Without it a healthy graph is never overwritten |
| `prune-quarantine --days N` | `30` | Retention: remove quarantines that are **genuinely unreadable** and older than N days. `recoverable` and `locked` files are never removed |

Why not just purge them: quarantined files are **not necessarily corrupt**. Code before COGNIREPO-97 quarantined an intact, encrypted graph whenever `keyring` was missing from the interpreter. `cognirepo doctor` only warns about a recoverable quarantine when `graph.pkl` is missing or unreadable; with a healthy graph they are listed under `-v` and left alone.

---

## cognirepo export-spec

Export OpenAI / Cursor tool specs to `adapters/` and print the OpenAI tools JSON on stdout, so `cognirepo export-spec > spec.json` works.

```bash
cognirepo export-spec
```

---

## cognirepo update-directives

Regenerate the agent directive files from the current templates.

```bash
cognirepo update-directives
```

Detects which agents are present in the project and rewrites `CLAUDE.md`, `GEMINI.md`, `.cursor/rules/cognirepo.mdc` and `.github/copilot-instructions.md` with the latest template content (overwriting them).

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

## cognirepo coverage

Show per-directory symbol counts from the AST index. Useful for spotting directories that were silently skipped during indexing (e.g. `backend/`, `routes/`).

```bash
cognirepo coverage
```

Language-agnostic: a source directory is any directory containing a file of an indexed language. Exit code `0` when every top-level source directory has at least one symbol, `1` when one or more have none (likely missed).

---

## cognirepo graph-stats

Node and edge counts and health of the knowledge graph (the same data as the MCP `graph_stats` tool).

```bash
cognirepo graph-stats
```

---

## cognirepo install-hooks

Write the git post-commit hook that keeps the index fresh: it runs `cognirepo index-repo --files <changed> --no-watch --no-embed` in the background after each commit.

```bash
cognirepo install-hooks
```

Idempotent. An outdated cognirepo block is replaced in place and any lines of your own in the hook are left alone. The extension filter is generated from the language registry, so re-run it after upgrading to pick up new languages. Output and the outcome of each run go to `.cognirepo/hook.log` and `.cognirepo/hook.last`; `cognirepo doctor` warns about a failed run or an outdated block. Exits `1` outside a git repository.

---

## cognirepo uninstall-hooks

Remove the cognirepo block from `.git/hooks/post-commit`.

```bash
cognirepo uninstall-hooks
```

Other lines in the hook are kept; if nothing else is left the hook file is removed. Does nothing (exit `0`) if no cognirepo block is present; exits `1` outside a git repository.

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
