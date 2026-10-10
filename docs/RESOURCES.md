# Resource footprint

What a CogniRepo install costs in memory and disk, how to see it, and what to turn when it is too much.
`cognirepo doctor --resources` prints the live picture (below); this page says what to expect.

## See where it goes

```bash
cognirepo doctor --resources          # human-readable
cognirepo doctor --resources --json   # for scripts
```

Read-only. Three sections:

* **Processes** — every running cognirepo process: command (`watch`, `serve`, `init`, …), resident memory,
  age, repo, and whether it looks stale (its directory was deleted, or a one-shot command has run for
  hours). Linux only (`/proc`).
* **Stores** — size of each `.cognirepo/` subdirectory, biggest first, with its largest files.
* **Set-aside and left-over files** — quarantines (`*.corrupt-*`), `*.replaced-*`, `*.stale` indexes and
  scratch files: bytes nobody is using and nobody deleted.

## Expected footprint

Measured on this codebase (≈250 Python files, ≈3,700 symbols), Linux, Python 3.14. They scale with the
repo, not with how long CogniRepo has been running — if a number below keeps growing for you, that is a bug
worth reporting.

| What | Typical | Notes |
|---|---|---|
| Background **watcher** (`watch --foreground`, or started by `index-repo --daemon`) | **~100–130 MB** resident | A fresh process that loads only the graph and index. Before #127 a watcher forked from `index-repo` carried the whole indexing heap (3.5 GB measured). |
| `cognirepo serve` (MCP server, one per agent session) | **~220 MB** idle | Includes its watcher thread when it holds the repo's watcher lease. Sessions that do not hold the lease stand by and load nothing extra (#138). |
| `index-repo --no-embed`, whole repo | **~125 MB peak** | Parse + graph only. |
| `index-repo` with embeddings | peak is dominated by the embedding model — an ONNX session of roughly **2 GB** resident (recorded in COGNIREPO-107) | The code evicts the model before saving the graph to stay under the circuit breaker. |
| `.cognirepo/` after a full index of this repo | **~7 MB** (`index/` 4.7 MB, `graph/` 2.4 MB) without embeddings | Add `vector_db/` (Chroma) if you store semantic memory and embed. |
| `graph/behaviour.json` | **bounded, a few MB** | Capped since #118: 2,000 queries, 50 sessions × 200 files, 30 co-edit partners per file. It was 77 MB before. |

At most **one watcher per repo** runs, whatever the number of sessions (#138); more than one cognirepo
process per repo that is not a `serve` session is worth a look in `doctor --resources`.

## Where the disk goes

| Directory | What | Grows with |
|---|---|---|
| `index/` | `ast_index.json`, `ast.index` (FAISS), `ast_metadata.json`, `manifest.json` | symbols in the repo |
| `graph/` | `graph.pkl`, `graph.journal` (only during `index-repo`), `behaviour.json` | graph size; behaviour is capped |
| `vector_db/` | Chroma store (semantic memory) | memories stored |
| `memory/`, `episodic/`, `learnings/`, `sessions/` | small JSON stores | usage, with caps (e.g. `episodic_max_events`) |
| `watchers/` | registry, heartbeat, lease, logs | tiny (one log file per watcher start) |

### Set-aside files — read before deleting
* `graph/graph.pkl.corrupt-<ts>` is **not necessarily corrupt**. Older versions set aside an intact
  encrypted graph whenever `keyring` was missing. Run `cognirepo graph restore` (dry-run) to see which
  can be restored; `cognirepo graph prune-quarantine` removes only the genuinely unreadable ones.
* `vector_db/chroma.corrupt-<ts>/` is a Chroma store the loader set aside after it failed to open.
* `*.stale` is a FAISS binary built on another platform/version; re-run `index-repo`.
* `*.replaced-<ts>` is a graph that `graph restore --force` replaced.

## Tuning knobs

| Knob | Where | Effect |
|---|---|---|
| `--no-embed` | `index-repo` | Skip embeddings: no model in memory, no vectors. Symbol lookup and the graph still work. |
| `--no-graph` | `index-repo` | Skip the knowledge graph (large repos). |
| `--tier N` | `index-repo` | Limit how much of a large repo is deeply indexed. |
| `indexing.max_file_bytes` | `config.json` | Skip files larger than this. |
| `indexing.skip_dirs` / `unskip_dirs` | `config.json` | Directories to leave out / put back. |
| `indexing.graph_journal*`, `indexing.writer_wait_secs` | `config.json` | Journal flush cadence while indexing; how long a second indexer waits for the writer lease. |
| `COGNIREPO_CB_RSS_LIMIT_MB` / `circuit_breaker.rss_limit_mb` | env / `config.json` | Circuit-breaker ceiling (default `min(80 % of RAM, 3072 MB)`); `index-repo` raises it to 4000 for itself. When it trips, heavy operations stop instead of the kernel killing the process. |
| `COGNIREPO_CB_COOLDOWN_SEC` | env | Seconds the breaker stays open before a probe. |
| `idle_ttl_seconds` | `config.json` | After this long without an MCP tool call, `serve` releases heavy resources (default 600). |
| `watch.auto_enabled` | `config.json` | `false`: `serve` does not start its in-process watcher. |
| `COGNIREPO_NO_WATCHER` | env | Any value: `init`, `index-repo --daemon` and `serve` start no background watcher (CI, containers, tests). |
| `indexing.debounce_ms` | `config.json` | Watcher batching window — larger means fewer saves. |

## When something is large

| Symptom in `doctor --resources` | Likely cause | Do |
|---|---|---|
| Several `init` / `watch` processes, some marked STALE | watchers of deleted repos (older versions) | `kill` the pids `cognirepo doctor` prints; update cognirepo |
| One `watch` over ~500 MB | an old forked daemon, or a very large repo | restart it: `cognirepo list -n <pid> --stop`, then `watch --ensure-running` |
| `graph/behaviour.json` tens of MB | pre-#118 file | it shrinks on the next load/save |
| Large `*.corrupt-*` entries | quarantines | see "Set-aside files" above before deleting |
| `index/` much larger than the source | binary or generated files indexed | `indexing.skip_dirs`, `indexing.max_file_bytes` |
