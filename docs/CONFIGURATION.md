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
  },
  "redis": {
    "enabled": false
  }
}
```

> **Single-model shorthand:** `cognirepo init` may write a simplified `"model": {"provider": "anthropic", "model": "claude-sonnet-4-6"}` form. This is auto-expanded to the four-tier registry at runtime. Use `cognirepo migrate-config` to canonicalise to the full form.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `project_name` | string | auto-detected | Human-readable project name |
| `port` | int | `8000` | REST API port |
| `storage.encrypt` | bool | `false` | Enable AES-256 encryption at rest |
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
| `indexing.debounce_ms` | int | `500` | File-watcher debounce window: events for the same path within this window collapse into one re-index/remove, and all pending changes in a batch are persisted with a single save. `0` disables batching — every event is processed synchronously and individually. |
| `indexing.graph_journal` | bool | `true` | Journal knowledge-graph mutations to `graph/graph.journal` while `index-repo` runs, so an interrupted run or a failed final `graph.pkl` save does not lose the indexed graph (COGNIREPO-109). `false` restores the old single end-of-run save. |
| `indexing.graph_journal_flush_files` | int | `200` | Flush the journal roughly every this many files' worth of graph changes (~25 ops/file). |
| `indexing.writer_wait_secs` | float | `0` | A second `index-repo` while another one holds the graph writer lease (`graph/graph.journal.writer`) refuses immediately with the owner's pid (`0`), or queues behind it for up to this many seconds (COGNIREPO-137). |
| `indexing.graph_journal_flush_secs` | float | `30` | Also flush when this many seconds passed since the last flush. |
| `behaviour_decay.half_life_days` | float | `30` | Half-life for the exponential recency decay applied to symbol `behaviour_score` (COGNIREPO-701) — a symbol hit this many days ago scores half of an otherwise-identical symbol hit "now". `<= 0` disables decay entirely (behaviour score behaves exactly as before). |
| `redis.enabled` | bool | `false` | Enable Redis caching layer |

---

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `COGNIREPO_REDIS_URL` | Redis connection URL | `redis://localhost:6379` |
| `COGNIREPO_ENCRYPT_KEY` | Encryption key (overrides keychain) | `<hex-encoded AES key>` |
| `COGNIREPO_JWT_SECRET` | JWT signing secret for REST API | `<random hex 32 bytes>` |
| `COGNIREPO_PASSWORD_HASH` | Bcrypt hash of the API password | `$2b$12$...` |
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
  index/                    ← AST symbol index
    ast_index.json          ← full AST index + reverse_index dict (ast_indexer.py)
    ast_metadata.json       ← parallel FAISS metadata for AST vectors
  sessions/                 ← conversation session history
  errors/                   ← error logs (date-stamped)
    2026-04-03.log
```

---

## Encryption at Rest

When `storage.encrypt: true`:

1. AES-256 GCM key is generated on first `cognirepo init`
2. Key is stored in the **OS keychain** (never written to disk)
3. All data in `vector_db/`, `graph/`, and `index/` is encrypted at rest
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

## Redis Cache

When `COGNIREPO_REDIS_URL` is set, CogniRepo uses Redis to cache:
- `retrieve_memory` results (keyed by `retrieve:{hash(query, top_k)}`)
- `lookup_symbol` results (keyed by `lookup_symbol:{name}`)

Cache TTL defaults to 300 seconds. The REST API gracefully degrades if Redis is unavailable.

```bash
export COGNIREPO_REDIS_URL=redis://localhost:6379
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

## Systemd Auto-restart (Linux)

CogniRepo can write a systemd user unit file:
```bash
cognirepo init  # answer "y" to systemd prompt
# or
systemctl --user enable ~/.config/systemd/user/cognirepo-watcher.service
systemctl --user start cognirepo-watcher
```

To check watcher status:
```bash
systemctl --user status cognirepo-watcher
cognirepo doctor  # shows heartbeat age
```
