# CogniRepo Configuration Reference

CogniRepo reads its configuration from `.cognirepo/config.json` in the project root.

---

## config.json Fields

```json
{
  "project_name": "my-project",
  "port": 8000,
  "storage": {
    "encrypt": false,
    "vector_backend": "chroma"
  },
  "models": {
    "QUICK":    {"provider": "local",     "model": "local-resolver"},
    "STANDARD": {"provider": "anthropic", "model": "claude-haiku-4-5"},
    "COMPLEX":  {"provider": "anthropic", "model": "claude-sonnet-4-6"},
    "EXPERT":   {"provider": "anthropic", "model": "claude-opus-4-6"}
  },
  "retrieval_weights": {
    "vector":    0.5,
    "graph":     0.3,
    "behaviour": 0.2
  },
  "idle_ttl_seconds": 600,
  "episodic_max_events": 10000,
  "indexing": {
    "skip_dirs": [],
    "unskip_dirs": [],
    "debounce_ms": 500
  },
  "behaviour_decay": {
    "half_life_days": 30
  }
}
```

> **Single-model shorthand:** `cognirepo init` may write a simplified `"model": {"provider": "anthropic", "model": "claude-sonnet-4-6"}` form. This is auto-expanded to the four-tier registry at runtime. Use `cognirepo migrate-config` to canonicalise to the full form.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `project_name` | string | auto-detected | Human-readable project name |
| `storage.encrypt` | bool | `false` | Enable Fernet encryption at rest. Covers the graph, behaviour model, org graph, episodic log, learnings, org project memory and the local FAISS store's text; **not** the AST index, vector files or the default Chroma store — see `SECURITY.md` |
| `storage.graph_backend` | string | `"networkx"` | Knowledge-graph store: `"networkx"` (default: `graph/graph.pkl` loaded whole into each process) or `"sqlite"` (opt-in: `graph/graph.sqlite`, WAL, read on demand — see [ADR 002](adr/002-sqlite-graph-store.md)). The first open with `sqlite` imports an existing `graph.pkl` in one transaction and leaves the pickle untouched, so switching back is just the flag. **`storage.encrypt: true` always uses `networkx`** (the SQLite file is not encrypted); `cognirepo doctor` reports when that overrides your choice. `COGNIREPO_GRAPH_BACKEND` overrides the file (tests, one-off runs). **Switch with `cognirepo graph migrate --to sqlite|networkx` (or the console's Controls → Graph storage) rather than editing this key**: it copies, verifies and only then changes the setting, and running agents follow it. **The two stores are not kept in sync**: the pickle is imported once, so changes made under one backend are invisible to the other if you switch back and forth. `cognirepo doctor` warns when both files exist and the unused one is newer; re-run `index-repo` (or delete `graph.sqlite` to import the pickle again) to resync. |
| `storage.vector_backend` | string | `"chroma"` | Vector backend: `"chroma"` (default; `init` writes it, and it is used when the key is absent) or `"faiss"`. Falls back to faiss only if `chromadb` isn't installed. |
| `models.QUICK.model` | string | `"local-resolver"` | Zero-API local resolver for trivial queries |
| `models.STANDARD.model` | string | `"claude-haiku-4-5"` | Model for quick lookups (score ≤4) |
| `models.COMPLEX.model` | string | `"claude-sonnet-4-6"` | Model for moderate reasoning (score ≤9) |
| `models.EXPERT.model` | string | `"claude-opus-4-6"` | Model for cross-file/architectural queries (score >9) |
| `retrieval_weights.vector` | float | `0.5` | Weight for FAISS vector score |
| `retrieval_weights.graph` | float | `0.3` | Weight for knowledge-graph hop score |
| `retrieval_weights.behaviour` | float | `0.2` | Weight for behaviour access-frequency score |
| `idle_ttl_seconds` | int | `600` | Inactivity timeout before heavy resources are released |
| `episodic_max_events` | int | `10000` | Max episodic events before oldest 20% rotate to `episodic_archive.json` |
| `indexing.skip_dirs` | list | `[]` | Extra directory names to skip during indexing (merged with built-in defaults) |
| `indexing.unskip_dirs` | list | `[]` | Built-in-skipped directories to index anyway (e.g. `["gen"]`) |
| `indexing.queue_max` | int | `5000` | Most distinct paths the watcher queue holds. A full queue never blocks the event thread: new paths are not queued, and once the queue drains a catch-up scan (git-based, like the one at watcher start) re-queues whatever changed, so the index still converges on the filesystem. Needs a git repo for that scan; without one an overflow is logged and some changes wait for the next `index-repo` |
| `indexing.batch_max` | int | `500` | Most files indexed per save. A big burst (a branch switch) is processed in several batches instead of one giant one, so results become searchable after the first batch and no single flush holds the watcher for minutes. Each batch costs one index + graph save, so a smaller value means more saves |
| `indexing.max_latency_ms` | int | `5000` | A constant stream of edits can keep resetting the debounce window; the watcher flushes anyway once the oldest queued path has waited this long |
| `indexing.debounce_ms` | int | `500` | File-watcher debounce window: events for the same path within this window collapse into one re-index/remove, and all pending changes in a batch are persisted with a single save. `0` disables batching — every event is processed synchronously and individually. |
| `indexing.graph_journal` | bool | `true` | Journal knowledge-graph mutations to `graph/graph.journal` while `index-repo` runs, so an interrupted run or a failed final `graph.pkl` save does not lose the indexed graph (COGNIREPO-109). `false` restores the old single end-of-run save. |
| `indexing.graph_journal_flush_files` | int | `200` | Flush the journal roughly every this many files' worth of graph changes (~25 ops/file). |
| `indexing.writer_wait_secs` | float | `0` | A second `index-repo` while another one holds the graph writer lease (`graph/graph.journal.writer`) refuses immediately with the owner's pid (`0`), or queues behind it for up to this many seconds (COGNIREPO-137). |
| `indexing.delete_grace_secs` | float | `60` | A file deleted in a commit is hidden from retrieval at once and purged (vectors, graph, index records) after this many seconds, on the next hook run, watcher flush or `index-repo`. A file that reappears inside the window is simply kept. `0` purges immediately (COGNIREPO-169). |
| `indexing.graph_journal_flush_secs` | float | `30` | Also flush when this many seconds passed since the last flush. |
| `daemon.enabled` | bool | `false` | **Global** setting (`~/.cognirepo/config.json` → `daemon`, or env `COGNIREPO_DAEMON=1`): `cognirepo serve` becomes a thin proxy to the per-user daemon. POSIX only; ignored (with a `doctor` note) elsewhere. See [DAEMON.md](DAEMON.md) |
| `daemon.idle_exit_secs` | int | `900` | The supervisor exits after this long with no workers and no clients |
| `daemon.worker_idle_secs` | int | `600` | A repo worker exits after this long with no connected agent |
| `daemon.max_workers` | int | `4` | Repo workers kept at once; an idle one is replaced, one with connected agents is never evicted (the new repo falls back in-process) |
| `daemon.worker_concurrency` | int | `2` | Tool calls a worker runs in parallel (an in-process `serve` runs one at a time) |
| `daemon.connect_timeout_secs` / `request_timeout_secs` / `spawn_timeout_secs` | float | `3` / `120` / `60` | Client-side limits; a daemon that exceeds them is treated as absent |
| `prune.auto_enabled` | bool | `false` | Run `prune` automatically from `cognirepo serve` (see [UI_API.md](UI_API.md#prune-service)). Off by default: it deletes memories |
| `prune.every_hours` | int | `24` | Interval between scheduled prunes (also read from `prune_schedule.json`). One run per interval across processes |
| `prune.archive` | bool | `true` | Scheduled runs move pruned memories to `archive/` (encrypted when `storage.encrypt` is on) instead of deleting them |
| `prune.threshold` | float | `0.15` | Score below which a scheduled run prunes a memory. Memories carry no timestamp, so the score is their importance |
| `behaviour.max_query_history` | int | `2000` | Query-history entries kept in `graph/behaviour.json` (newest kept). Only recent windows (5–20 min) are ever read; what queries taught retrieval is stored in `symbol_weights`, which is never pruned. |
| `behaviour.max_sessions` | int | `50` | Watcher sessions kept in the session registry (newest kept). |
| `behaviour.max_files_per_session` | int | `200` | Files remembered per session; also bounds the co-edit fan-out. |
| `behaviour.max_cooc_partners` | int | `30` | Strongest co-edited partner files kept per file. |
| `behaviour.max_terms` | int | `500` | Most frequent query terms kept. |
| `behaviour.max_query_text` / `max_retrieved_per_query` / `max_error_files` | int | `500` / `20` / `20` | Per-entry size limits. All `behaviour.*` values must be integers ≥ 1; anything else falls back to the default. Going over a bound drops the oldest entries of that one section and logs it (INFO when 100+ are dropped at once). |
| `behaviour_decay.half_life_days` | float | `30` | Half-life for the exponential recency decay applied to symbol `behaviour_score` (COGNIREPO-701) — a symbol hit this many days ago scores half of an otherwise-identical symbol hit "now". `<= 0` disables decay entirely (behaviour score behaves exactly as before). |

---

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `COGNIREPO_LOCK_HOLD_WARN_SECS` | A store lock held longer than this many seconds is logged (WARNING) when released, with its duration. Default `10` | `5` |
| `COGNIREPO_LOCK_STRICT` | Any value: taking a second, different store lock while holding one raises `LockOrderError` instead of logging a warning. For tests / debugging; see `docs/architecture/GRAPH_CONCURRENCY.md` | `1` |
| `COGNIREPO_NO_WATCHER` | If set (any value), `init` / `index-repo --daemon` do not start a background watcher and `serve` does not start its in-process one. For CI, containers and the test suite | `1` |
| `COGNIREPO_PROGRESS_FILE` | Path of a JSON file that `index-repo --files` / `--changed-only` keeps updated with `{"done", "total"}`. Set only by the `cognirepo ui` index service (#211); unset (the default) it does nothing | unset |
| `COGNIREPO_ENCRYPT_KEY` | Encryption key (overrides keychain) | `<hex-encoded AES key>` |
| `ANTHROPIC_API_KEY` | Anthropic/Claude API key | `sk-ant-...` |
| `GEMINI_API_KEY` | Google Gemini API key | `AIza...` |
| `GOOGLE_API_KEY` | Gemini (alternate key name) | `AIza...` |
| `OPENAI_API_KEY` | OpenAI API key | `sk-...` |
| `GROK_API_KEY` | Grok API key | `...` |

---

## Storage Layout

```
.cognirepo/
  config.json               ← project settings (this file)
  vector_db/                ← semantic vector store
    chroma/                 ← default backend (chromadb PersistentClient), incl. `.next_id` id counter,
                               `.open.<pid>` markers (live openers) and `.opening.<pid>` sentinels (crash evidence)
    chroma.lock             ← cross-process lock: store creation, id allocation, sentinel healing
    chroma.corrupt-<ts>/    ← a store that crashed on open and was quarantined (kept, never deleted)
    semantic.index          ← faiss backend only: FAISS IndexFlatL2 binary (local_vector_db.py)
  memory/                   ← embeddings metadata + episodic log
    semantic_metadata.json  ← per-vector metadata (text, source, importance, timestamp)
    episodic.json           ← append-only episodic event journal (JSON lines)
    episodic_archive.json   ← rotated events when episodic_max_events is exceeded
    episodic_vecs.npy       ← cached entry embeddings for semantic episodic search
                               fallback, keyed by event id (episodic_vecs_ids.json
                               sidecar); regenerable — safe to delete
    episodic_vecs_ids.json  ← id list, row-aligned with episodic_vecs.npy
  graph/                    ← knowledge graph
    graph.pkl               ← serialised NetworkX DiGraph
    graph.journal           ← append-only mutation journal written during indexing; replayed on
                               load and removed when save() compacts it into graph.pkl
                               (encrypted per segment when storage.encrypt is on)
    graph.journal.writer    ← OS lock file: the single-writer lease held by a running index-repo
    graph.journal.writer.pid← pid of the lease holder (for the "already running" message)
    graph.sqlite            ← only with storage.graph_backend = "sqlite": the graph as nodes/edges tables
                               (plus graph.sqlite-wal / -shm while open). Replaces graph.pkl and the journal;
                               an index run still takes graph.journal.writer.
  index/                    ← AST symbol index
    ast_index.json          ← full AST index + reverse_index dict (ast_indexer.py)
    ast_metadata.json       ← parallel FAISS metadata for AST vectors
    tombstones.json         ← deleted files hidden from retrieval, awaiting purge (absent when none)
  sessions/                 ← conversation session history
  errors/                   ← error logs (date-stamped)
    2026-04-03.log
```

---

## Encryption at Rest

When `storage.encrypt: true`:

1. A Fernet key (AES-128-CBC + HMAC-SHA256) is generated on first `cognirepo init`
2. Key is stored in the **OS keychain** (never written to disk)
3. The graph, behaviour model, org graph, episodic log, learnings, org project memory and the local FAISS store's memory text are encrypted. The default Chroma store, vector files and the AST index are **not** — see `SECURITY.md#encryption-at-rest` for the full table (`core/security/coverage.py` is the source of truth). `cognirepo encrypt-stores` migrates learnings/project memory on demand
4. The `cryptography` package is required: `pip install cognirepo[security]`

**Keychain backends by platform:**
| Platform | Backend |
|----------|---------|
| macOS | Keychain Access (via `keyring`) |
| Linux | Secret Service (KWallet / GNOME Keyring) |
| Windows | Windows Credential Manager |

**To enable encryption:**
```bash
pip install cognirepo[security]
# Edit .cognirepo/config.json:
# "storage": { "encrypt": true }
cognirepo init  # re-run to generate and store the key
```

---

## MCP Server Configuration

### Claude Desktop (`.claude/CLAUDE.md`)
The `.claude/CLAUDE.md` file is auto-generated by `cognirepo init` and provides tool-first workflow instructions.

### Cursor (`.cursor/mcp.json`)
```json
{
  "mcpServers": {
    "cognirepo-my-project": {
      "command": "python",
      "args": ["-m", "cognirepo", "serve", "--project-dir", "/path/to/project"]
    }
  }
}
```

### VS Code (`.vscode/mcp.json`)
```json
{
  "servers": {
    "cognirepo-my-project": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "cognirepo", "serve", "--project-dir", "/path/to/project"]
    }
  }
}
```

Run `cognirepo init` to auto-generate these files.

---

## Always-on watcher (`watch --autostart`)

```bash
cognirepo watch --autostart on    # or answer "y" to the prompt in `cognirepo init` (default: No)
cognirepo watch --autostart off   # removes the service
```
One service per repo, named `cognirepo-watcher-<dir>-<hash>`; both directions are idempotent.

| OS | What is installed | Crash handling |
|----|-------------------|----------------|
| Linux | systemd user unit `~/.config/systemd/user/<name>.service`, `enable --now` | `Restart=on-failure`: a crash or `kill -9` is revived after 10 s; a clean stop (`cognirepo list --stop`, `systemctl stop`) stays stopped |
| macOS | launchd agent `~/Library/LaunchAgents/io.cognirepo.<name>.plist` | `KeepAlive.SuccessfulExit=false`, same semantics |
| Windows | Task Scheduler task `CogniRepo\<name>`, at logon | start-at-logon only; `schtasks` cannot set restart-on-failure, so the catch-up scan covers the gap |

The service runs `cognirepo watch --path <repo> --serve`. Whenever a watcher starts it **catches up**: files
modified after their index record, and files deleted since, are re-indexed/removed before live events take
over. If a watcher you started by hand is running, enabling autostart stops it first so the service can
take the per-repo lease. The older `generate_systemd_unit()` / `.cognirepo/cognirepo-watcher.service`
file is still produced by the Python API but is no longer what `init` offers.

The unit runs `cognirepo watch --path <repo> --serve`: the watcher stays in the foreground
(registered like a forked daemon, so `cognirepo list` / `watch --status` see it), logs to stderr
(`journalctl --user -u cognirepo-watcher`), and `TimeoutStopSec=60` leaves room for its final flush
(it forces exit after 20 s). Units generated by older versions used `--daemon-foreground`, which
is still accepted as an alias.

To check watcher status:
```bash
systemctl --user status cognirepo-watcher
cognirepo doctor  # shows heartbeat age
```
