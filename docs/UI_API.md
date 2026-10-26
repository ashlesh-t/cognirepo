# Local control API (`cognirepo ui`)

A small HTTP API plus launcher for a local console. **Local-only by design**: it binds to loopback,
needs a per-session secret, and exposes no endpoint that reads arbitrary files or runs arbitrary
commands. The machine-readable contract is [`docs/openapi/ui-v1.json`](openapi/ui-v1.json)
(regenerate with `python -m interface.ui.openapi --write`; a test fails if it drifts).

## Quick start

Requires the optional `[ui]` extra (fastapi, uvicorn): `pip install 'cognirepo[ui]'`, or for a pipx install `pipx inject cognirepo 'cognirepo[ui]'`. Without it `cognirepo ui` prints this hint and exits 1 (`--stop` and `--autostart off` still work).

```bash
cognirepo ui                  # start the server if needed, open http://127.0.0.1:8731/#token=…
cognirepo ui --no-open        # print the tokenised URL instead of opening a browser
cognirepo ui --stop           # stop the server
cognirepo ui --autostart on   # opt in to starting at login (off by default); `--autostart off` removes it
```
Default port is `8731` (a free port is used if it is busy; an explicit `--port` that is busy is an error).
The server serves **the repo you launched it from**; a second repo needs `cognirepo ui --stop` first.

## Console install (git-managed, #215)
The web UI is a prebuilt static bundle. The server picks it in this order:
1. **`<global>/console/`** — a shallow clone of the `release` branch of
   `https://github.com/ashlesh-t/cognirepo-console`, verified against its `console.json` manifest;
2. the optional **`cognirepo-console`** pip package (`STATIC_DIR`);
3. a minimal status page (API only).

If `<global>/console/` is missing, `cognirepo ui` clones it once (plain `git`, argv list, no shell, a
fixed URL, `GIT_TERMINAL_PROMPT=0`, 120 s timeout, `ext::` transport disallowed) into a staging directory,
validates it, then renames it into place — a failed or refused fetch leaves nothing behind. This is the
**only** network call: it happens in the foreground `cognirepo ui` command, never in the server process, at
login (autostart) or in the background. Once installed it works offline. It needs `git` and network; without
them `cognirepo ui` prints one line and falls back to 2/3.

`console.json` must contain `{"name": "cognirepo-console", "version", "api_major", "files": {path: sha256}}`.
A bundle is **refused** (and the next source is used) if `api_major` differs from this server's
(`status.api_version`), a listed file is missing or its sha256 differs, `index.html` is not listed, or a path is
absolute, contains `..`, points into `.git/`, or is a symlink. Only files the manifest lists are served — `.git/`
and any other file in the directory answer 404. Validation runs when the server starts.

### Updating the console (#216)
Updates are explicit and one-shot — never automatic, no background network calls.

| Command | Does |
|---|---|
| `cognirepo ui --update --check` | Fetch and report `old -> new`; nothing in `<global>/console/` changes |
| `cognirepo ui --update` | Fetch, verify, swap in; the previous build is kept as `<global>/console.prev/` |
| `cognirepo ui --update --rollback` | Swap `console.prev/` back in (running it again toggles back) |

How an update stays safe: the live directory is copied to `console.new-<pid>/` and **all** git work happens in that copy
(`git fetch --depth 1 origin <ref>`; only `fetch`, `rev-parse`, `show` and `reset` ever run — no script from the fetched
tree). The copy's `console.json` must have the server's `api_major` (otherwise the update is refused and the message says
which API major this cognirepo serves) and the whole tree must pass the sha256 validation; only then are two renames
done (`console` → `console.prev`, staged → `console`). Any failure — network, git, refused build — removes the
staging copy and leaves the current build untouched. A request landing exactly between the two renames sees a 404.

Deviation from a literal fast-forward: a depth-1 fetch has no history, so `git merge --ff-only` always fails
("unrelated histories"), and the release branch is rebuilt by CI. The staged copy is instead reset to the fetched commit;
the safeguard is the manifest validation above, not git history. Pin a tag/branch with `COGNIREPO_CONSOLE_REF` or
`ui.console_ref`; the update always fetches from the clone's own `origin` (to change source, delete the directory).

A running server needs no restart: static files are read per request and it re-reads `console.json` when it changes.
Refresh the page. Without `<global>/console/` as a git clone (e.g. only the pip package), `--update` says so.

Trust model: the hashes detect corruption and local tampering of an installed bundle; they do not authenticate the
repo, because the manifest comes from the same clone. Trust is therefore in the source URL.

| Setting | Env var | `<global>/config.json` → `ui` | Default |
|---|---|---|---|
| Source repo | `COGNIREPO_CONSOLE_REPO` | `console_repo` | the URL above |
| Branch or tag | `COGNIREPO_CONSOLE_REF` | `console_ref` | `release` |
| Fetch when missing | `COGNIREPO_CONSOLE_AUTOFETCH=0` | `console_autofetch: false` | on |

`cognirepo ui --no-console-fetch` skips the fetch for one run. The setting is read from the environment or your own
global config, never from a request. A directory that exists but fails validation is **not** overwritten; the
message names the reason.

## Authentication
1. `cognirepo ui` opens `http://127.0.0.1:PORT/#token=<secret>`. The fragment is never sent to a server.
2. The page script (`/_cognirepo/bootstrap.js`, or the console's own) **strips the fragment first**, then
   `POST /api/v1/session {"token": …}`; the server answers with an `httpOnly; SameSite=Strict` cookie `cr_session`.
3. Every `/api/v1/*` request needs that cookie **or** `Authorization: Bearer <token>`. Comparison is constant-time.
4. The token lives for the server's lifetime in `<global dir>/ui/session.json` (mode 0600, removed on shutdown).

The only token-less responses are the data-free landing page / static console assets and the
`/_cognirepo/bootstrap.js` script. `POST /api/v1/session` takes the token in its body instead of a header.

## Endpoints (`/api/v1`)
| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/session` | Swap `{token}` for the session cookie |
| `GET` | `/api/v1/status` | Version, repo, watcher daemon health, MCP tool inventory, indexer status |
| `GET` | `/api/v1/graph?node=&depth=&limit=` | Read-only knowledge-graph slice. `depth` 0–3 (default 1), `limit` 1–2000 (default 200). Without `node`: the highest-degree nodes. Only whitelisted attributes are returned |
| `GET` | `/api/v1/harness` | Which agent clients (Claude Code, Cursor, VS Code, Gemini CLI) have the CogniRepo MCP server configured — names only, never args/env — plus a fixed-field summary of the shared last context (no query text) |
| `GET` | `/api/v1/insights` | `{exists, generated_at, bytes}` for the repo's insights report (`.claude/insights/<repo>-insights.html`) |
| `GET` | `/api/v1/insights/report` | The report HTML, read-only, from that one fixed path (no path/name parameter exists). Sent with `Content-Security-Policy: sandbox; default-src 'none'` so it can sit in an `<iframe sandbox>` (`frame-ancestors 'self'`); `?download=1` sends it as an attachment. `404 no_report` if absent, if the path is a symlink (or under one), or if it exceeds 8 MiB |
| `GET` | `/api/v1/events` | Live event stream (SSE). See [Event stream](#event-stream) |
| `GET` | `/api/v1/graph/changes?since=&limit=` | Knowledge-graph change feed (`seq`, `ops`, `reset`, `more`). See [Graph changes](#graph-changes) |
| `GET` | `/api/v1/repos` | Every repo in the global registry with index, watcher, hooks and auto-index state. See [Repos](#repos) |
| `GET` | `/api/v1/sessions` | MCP sessions (id, client, started, last_activity, call_count, closed_at, state). See [Sessions](#sessions) |
| `GET` | `/api/v1/sessions/{session_id}?limit=` | One session plus its last tool calls (default 100, max 500). `404 unknown_session` |
| `GET` | `/api/v1/processes` | CogniRepo processes for this repo (`ui`, `watcher`, live `mcp` servers) with RSS, threads and watcher heartbeat. See [Processes, audit and metrics](#processes-audit-and-metrics) |
| `GET` | `/api/v1/daemon` | The optional per-user daemon: supervisor and its repo workers. See [Daemon, queue and journal](#daemon-queue-and-journal) |
| `GET` | `/api/v1/queue?repo=` | The file watcher's queue for a repo (`running: false` when no watcher is running) |
| `GET` | `/api/v1/journal?tail=&types=&repo=` | Recent graph, prune, re-index and service events, oldest first |
| `GET` | `/api/v1/graph/backend?repo=` | Which graph store is in use (`networkx` / `sqlite`), what each file holds, whether the toggle is safe, and a recommendation. See [Graph storage backend](#graph-storage-backend) |
| `GET` | `/api/v1/graph/backend/job` | The graph migration job (`idle` / `running`, progress, last result) |
| `POST` | `/api/v1/graph/backend/switch` | The toggle. Body `{"to": "networkx"\|"sqlite", "confirm": true}`. Flips the setting if the target already holds an up-to-date graph, otherwise migrates first as a job; never switches onto stale data |
| `POST` | `/api/v1/graph/backend/migrate` | Migrate either way. Body `{"to", "replace": false, "dry_run": false, "confirm": true}`; `dry_run` returns the plan and changes nothing |
| `GET` | `/api/v1/audit?tail=` | Last `tail` (1–500, default 100) records of the control-API audit log, newest last |
| `GET` | `/api/v1/services` | State of the allowlisted services |
| `POST` | `/api/v1/services/{name}/start` | Start a service. Body must be `{"confirm": true}` (strict boolean) |
| `POST` | `/api/v1/services/{name}/stop` | Stop a service. Body must be `{"confirm": true}` |
| `POST` | `/api/v1/settings/auto-index` | Persist `watch.auto_enabled` for this repo. Body `{"enabled": bool, "confirm": true}`. See [Index and hooks](#index-and-hooks-services) |

**Service allowlist:** `watcher` (the repo's file-watcher daemon), `index` and `hooks` (see
[Index and hooks](#index-and-hooks-services)), `prune` (see [Prune](#prune-service)), `daemon` (start/stop the
per-user daemon, see below), `insights` (`start` regenerates the report by running `cognirepo insights`; one run at a time, `stop` is `409 not_stoppable`) and `metrics` (in-process Prometheus
`/metrics` on `127.0.0.1:9090`, see [Processes, audit and metrics](#processes-audit-and-metrics)). Any other name is a `404` before anything else is evaluated. Each service
maps to fixed code with a fixed argv — nothing from a request reaches a command line.

**Honest results:** a service action returns `state: "failed"` with a machine-readable `reason` (and a short `detail`)
instead of promising success. Watcher `start`: `not_initialised` (no `.cognirepo/config.json`), `disabled_by_env`
(`COGNIREPO_NO_WATCHER`), `spawn_failed` (the launcher exited non-zero; `detail` is the last line of its output, kept in
`<store>/watchers/ui-start.log`). `start` waits up to ~2 s for the watcher to register: `running` with its `pid`, or
`starting` if it is still loading. Watcher `stop` uses the same escalation as `cognirepo list --stop` (SIGTERM, then
SIGKILL, bounded to ~11 s): `stopped` (with `detail: "needed SIGKILL"` when escalated) or `failed`/`stop_failed`; a
watcher embedded in an MCP server is `409 embedded_watcher`. `metrics` start without `prometheus_client` is
`failed`/`dependency_missing`. The audit log records these as `result: "failed"`.

### Index and hooks services
The console can run an **incremental** index and manage the git hooks; both use the same `confirm` + allowlist + audit
model as the other services and the same lock rules as the CLI (writers serialise on the store lock; readers never wait).

| Service | `start` | `stop` | `state` |
|---|---|---|---|
| `index` | Runs `cognirepo index-repo --changed-only` (git-reported changes only; fixed argv, one run at a time, output kept in `<store>/watchers/ui-index.log`). A **full re-index is not exposed** | `409 not_stoppable` (a run finishes on its own) | `running` \| `idle` |
| `hooks` | Runs `cognirepo install-hooks` (idempotent; your own hook content is kept) | Runs `cognirepo uninstall-hooks` | `installed` \| `not_installed`; `failed`/`not_a_git_repo` outside a git repo |

`index` also reports `progress` (`{done, total}` files processed, while running) and `last_run`
(`{result, reason, exit_code, retryable, finished_at, duration_s, detail}`, cleared when a new run starts). Run state is
file-backed (`<store>/watchers/ui-index-run.json` while live, `ui-index-last.json` after), so it survives a UI-server
restart: a run started by the previous server is still reported `running` (and a second one is not started), and its
result is classified from the run's log when it ends (`exit_code` is then `null`). A run record older than 6 h is treated
as dead, which guards against a reused pid.
- `result: "busy"` / `reason: "store_busy"` / `retryable: true` — another writer holds the store (CLI exit 75, or an
  indexer holding the graph writer lease). This is not an error; retry in a moment.
- `result: "failed"` / `reason: "base_incomplete"` — there is no complete base graph, so an incremental run refuses to
  replace it with a fragment (COGNIREPO-122). Run one full `cognirepo index-repo .`.
- `result: "failed"` / `reason: "index_failed"` — anything else; `detail` is the tail of the output (for example the
  repo is not a git repo or has no commits, which `--changed-only` needs).

`GET /status` → `indexer` adds `graph_base_incomplete` (the watcher's latest batch skipped its graph save for the same
reason; `last_watcher_reindex.graph_skipped` carries the text; false until a batch has run, and cleared again once a
graph is written after that batch, e.g. by a full `index-repo`) and `auto_index`
(`watch.auto_enabled`, default true), and `watch_queue` (below). `last_watcher_reindex` (`timestamp`, `reindexed[]`, `removed[]`, `error`) is
there too.

`POST /api/v1/settings/auto-index` writes only `watch.auto_enabled` into `<store>/config.json` (read-modify-write under
the store lock, atomic replace; every other key is untouched) and answers `{auto_index, changed}`; `409 not_initialised`
without a `config.json`. When `cognirepo ui` starts and the setting is **explicitly `true`**, it starts the repo's watcher
(best-effort, off the request path, audited as `auto_index_start`). Absent — the default, which the MCP server treats as
on — does nothing at UI start.

### Prune service
`prune` removes low-importance semantic memories and orphan graph nodes — it deletes data, so the console must do it in
two steps:

1. `POST /services/prune/start` with `{"confirm": true, "dry_run": true}` runs `cognirepo prune --dry-run` and **returns
   what would be pruned** in `summary`: `total`, `kept`, `pruned`, `graph_stats.orphans_removed` and a `preview` of the
   lowest-scoring memories (`text` clipped to 80 characters, `score`, `age_days`; at most 50, `preview_truncated`).
   Nothing is changed. The preview text lives only in this response — it is never written to disk, the run log or the
   event. (`dry_run` on any other service is `400 dry_run_unsupported`.)
2. `POST /services/prune/start` with `{"confirm": true}` starts a detached run — **always archiving** (`archive/pruned_<ts>.json`,
   encrypted when `storage.encrypt` is on) — and only if a dry run completed within the last 30 minutes; otherwise
   `409 dry_run_required`. Progress is `state: running | idle`; `last_run` (`result` ok \| busy \| failed, `reason`,
   `retryable`, …) and `summary` (counts) survive a UI restart. A store held by another writer is `busy` / `store_busy`
   (retryable), memory pressure is `busy` / `memory_pressure`, anything else `failed` / `prune_failed`. `stop` is `409 not_stoppable`.

The state also carries `dry_run_fresh` (a real run is currently allowed) and `auto`: `{enabled, every_hours, archive,
next_due_in_s}` — the scheduled-prune settings below.

**Scheduled prune** is opt-in (`prune.auto_enabled`, default off; see CONFIGURATION.md) and runs inside `cognirepo serve`.
It is built so that it cannot do harm unattended: a non-blocking `prune.lock` plus the last-run time in `prune_state.json`
allow **one run per interval across all servers**; it is scheduled for when it is *due* (at least 60 s after start), so
short sessions still prune and a restart does not reset the clock; and it **archives by default** (`prune.archive: false`
opts out). The store is read, scored and rewritten under one store-lock hold, with vectors copied out of the existing
FAISS index — a memory stored concurrently is no longer lost, and no embedding model is needed.

### Watcher queue
`status.indexer.watch_queue` is the file watcher's queue as it last published it (`<store>/index/watch_queue.json`, written after each
batch, at most once a second otherwise) — `null` when no watcher is running (a dead watcher's numbers are not reported):
`depth` and `max` (capacity, `indexing.queue_max`), `oldest_age_s` (how long the oldest queued path has waited),
`enqueued`, `coalesced`, `dropped` and `overflows` (paths that did not fit, and how many times the queue filled up — each one
was followed by a catch-up scan), `batches`, `files` (processed so far), `last_batch` (`files`, `ms`), `max_depth`,
`batch_max`, `debounce_ms`, `pid`, `updated_at`. The same numbers are Prometheus series: `cognirepo_watcher_queue_depth`,
`..._oldest_age_seconds`, `..._capacity`, and the counters `..._overflows_total`, `..._dropped_total`, `cognirepo_watcher_batches_total`.

### Daemon, queue and journal
These three endpoints are what the console's Daemon, Queue and Live views read; all are read-only and token-gated.

**`GET /api/v1/daemon`** — `supported` (this platform has Unix sockets; false on Windows), `enabled` (`daemon.enabled` /
`COGNIREPO_DAEMON`), `running`, and when running: `version`, `pid`, `rss_bytes`, `socket`, `max_workers`, `started` and
`workers[]` — one per active repo: `repo`, `pid`, `alive`, `unresponsive`, `clients` (connected agent sessions), `calls`,
`rss_bytes`, `idle_secs`, `started`, `served` (the repo this UI server was started for). It only *asks* a running
supervisor (1.5 s timeout) — it never starts the daemon, and a wedged or absent one answers `running: false` fast.
`GET /api/v1/repos` entries carry the same worker as `daemon` (null when the daemon is not running or not serving that repo).

**`daemon` service** — `POST /api/v1/services/daemon/start` starts the supervisor (workers start on demand when agents
connect); `/stop` stops it **and every repo worker**, which drops all agents' shared workers (their proxies reconnect to a
fresh one on the next call while the daemon is enabled, or fall back to in-process). Both need `confirm: true` and are
audited. On a platform without Unix sockets the state is `unsupported` and `start` answers `failed` / `unsupported`.

**`GET /api/v1/queue?repo=`** — the watcher's queue as `status.indexer.watch_queue` (see [Watcher queue](#watcher-queue)) with a
`running` flag: `{"running": false}` when no watcher runs for that repo, else `{"running": true, depth, max, oldest_age_s,
overflows, dropped, batches, files, last_batch, ...}`. Cheap enough to poll (one small file read).

**`GET /api/v1/journal?tail=&types=&repo=`** — the last `tail` (1–500, default 100) events of the selected repo's log whose type
matches `types` (comma-separated globs; default `graph.delta,prune,watcher.reindex,service`), oldest first, in the event
schema below. It is a bounded slice of the event log (live file + one backup), not a durable audit trail. With
`COGNIREPO_EVENTS_METADATA_ONLY=1` graph deltas are `reset` markers without node ids, as everywhere else; with
`COGNIREPO_EVENTS=0` the list is empty. Follow the same events live with `GET /api/v1/events`.

### Graph storage backend

The graph can be stored as a pickle (`networkx`, the default) or in SQLite (see [ADR 002](adr/002-sqlite-graph-store.md)).
These routes let the console show and change that, with the same engine as `cognirepo graph migrate`
(`data/graph/migrate.py`); the console has no copy logic of its own.

* **`GET /graph/backend`** (`?repo=` allowed; `job` only for the served repo) returns `active` (what this server's
  environment resolves to), `configured` (what `config.json` says), `env_override` (`COGNIREPO_GRAPH_BACKEND` in the server
  process, which wins over the file), `forced_by_encryption` + `note`, `files` (`exists`, `bytes`, `mtime` of each
  backend's file; SQLite includes its WAL), `nodes` / `edges` (from the `graph.stats` sidecar, `null` before the first save),
  `stale_note` (set when the unused backend's file is newer), `recommendation` (`use`, `confidence` = `clear` / `leaning` /
  `either`, `reasons`), `sessions` (attached `cognirepo serve` processes), and the toggle's state: `can_toggle`,
  `toggle_blocker` (`env_override`, `encryption_on`, `job_running`, `not_initialised`), `switch_to`, `switch_needs_migration`.
* **`POST /graph/backend/switch`** is the toggle. If the target backend already holds an up-to-date graph (or there is
  nothing to carry over) it only changes `storage.graph_backend` (`action: "switched"`); otherwise it starts the migration
  job (`action: "migrating"`) and the setting changes only after the copy is verified; `"noop"` if already there. A stale
  target is set aside, not merged. Blocked states answer `409` with the blocker code.
* **`POST /graph/backend/migrate`** is the explicit control. `dry_run: true` runs `cognirepo graph migrate --dry-run`
  and returns the plan (`from`, `to`, `nodes`, `edges`, `ram_mb`, `needs_replace`, `moves_aside`, `blockers`) without
  changing anything; otherwise it starts the job (`{"started": bool, "job": …}`; one at a time).
* **`GET /graph/backend/job`**: `state`, `progress` (`phase`: prepare → copy → import/export → write → verify → switch → done,
  with `done` / `total`), `last_run` (`result` `ok` / `failed` / `busy`, `reason` = the CLI's error code such as
  `target_exists`, `no_source`, `verify_failed`, `watcher_not_stopped`, `encryption_on`), `summary`.

Writes need `confirm: true` (strict boolean) and are audited (`graph_backend_switch`, `graph_backend_migrate`); like all
writes they are for the served repo only (`409 not_served_repo`). The job runs `cognirepo graph migrate --json --stop-watcher`
with a fixed argv (only the validated backend name and the `replace` flag come from the request): it takes the index writer
lease (an index run makes it `busy`), stops and afterwards restarts a standalone watcher, copies, verifies and only then
switches the setting; a failed verification undoes the copy and changes nothing. Running agents, the watcher and cached
retrievers follow the new setting on their next call. Job files live in `<store>/jobs/`.

### Status codes
`200` ok · `400` `confirm_required` · `401` missing/invalid token · `403` bad `Host`/`Origin` · `404` unknown service/path ·
`409` `port_in_use` · `422` invalid parameters · `429` locked out (`Retry-After` seconds) · `501` unsupported platform.

### Stability
`/api/v1` is additive-only: fields may be added, never removed or retyped. A breaking change ships as `/api/v2`.

## Processes, audit and metrics
**`GET /api/v1/processes`** — one row per process: `role` (`ui`, `watcher`, `mcp`), `pid`, `state`, `rss_bytes`, `threads`
(from `psutil`; `null` when the process is gone or not inspectable), `heartbeat_age_s` (watcher), `detail` (mcp: the client
name) and `session_id` (mcp). The watcher comes from its registered heartbeat; `mcp` rows are MCP sessions that have not
ended and whose pid is alive (the pid is in the `session.start` event). `cognirepo serve` processes the event log does
not know about — older sessions without a pid, or events disabled — are found by a process scan (working directory equal
to the repo, `serve` command line; cached 5 s; processes the user cannot inspect are skipped) and listed with
`detail: "discovered by process scan"`. Read-only: it never removes stale pid files.

**`GET /api/v1/audit?tail=`** — the audit log's last records (what the Security model section describes; it never holds
the token).

**`GET /status` → `indexer.store_bytes`** — bytes per top-level store directory, `_files` (loose files such as config and
lock), and `total`. Cached for 30 s so a polling console does not re-walk the store.

**Metrics.** The standalone `/metrics` server (`cognirepo metrics`, or the `metrics` service) reads the store, not process
memory — the MCP server, the watcher and the metrics server are different processes and cannot share in-process counters.
Every number below is derived on scrape from files each process already writes; there is no multiprocess directory and
nothing extra on the hot paths. All series carry a `repo` label (the served repo's name).

| Series | Source |
|---|---|
| `cognirepo_tool_calls_total{tool,outcome}` (`ok`, `error`, `busy`, `shed`) | `tool.*` events |
| `cognirepo_tool_call_duration_seconds{tool}` (histogram; shed calls excluded) | `tool.end` / `tool.error` `dur_ms` |
| `cognirepo_store_busy_total` | `tool.error` with `StoreBusy` |
| `cognirepo_graph_seq`, `cognirepo_graph_nodes`, `cognirepo_graph_edges` | `graph/graph.seq`, `graph/graph.stats` (written after each graph save) |
| `cognirepo_index_age_seconds`, `cognirepo_index_files`, `cognirepo_index_symbols`, `cognirepo_index_vectors` | `index/manifest.json` (`vector_count` is written by every index save from now on; older manifests omit it) |
| `cognirepo_watcher_up`, `cognirepo_watcher_heartbeat_age_seconds` | watcher registry + heartbeat (read-only) |
| `cognirepo_store_bytes{part}`, `cognirepo_event_seq`, `cognirepo_event_log_age_seconds` | directory sizes, event log (the age is omitted when there are no events; a large value means idle or events disabled) |
| `cognirepo_events_missed_total` | events that rotated out of the log before they were counted |

The tool-call tallies and a cursor (the last event `seq`) are checkpointed to `<store>/metrics/state.json` after any
scrape that saw new events (atomic; nothing else writes it). A restarted metrics server resumes from the cursor, so the
counters are cumulative across restarts and independent of how much of the event log is retained; a fresh store starts
from the retained log (live file plus one backup, ~10 MiB). If the log rotated past the cursor while nobody was
scraping, the lost events are counted in `cognirepo_events_missed_total` rather than hidden. A checkpoint that is
corrupt, from another version, or ahead of the log (the store was wiped) is ignored and counting starts fresh. With
`COGNIREPO_EVENTS=0` the tool series stay empty; `cognirepo_event_log_age_seconds` tells that apart from an idle repo.
Gauges whose source file does not exist yet (graph stats before the first save, index age before the first index) are
omitted rather than reported as 0. The old in-process counters in `core/metrics.py` (`cognirepo_memory_ops_total`, cache
and breaker gauges) are no longer served here: they were always 0 in this process. Semantic-memory vector counts are not
exposed (its store has no single save point to record them at).

## Event stream
`GET /api/v1/events` is a `text/event-stream` fed by `<store>/events/events.jsonl` (mode 0600, rotated at 5 MiB with one
`.1` backup). MCP tool calls, watcher re-indexes and service start/stop append to it; this process only reads it.
Same auth as every other endpoint (token or cookie, Host/Origin checks, lockout); `Cache-Control: no-store`.

* `id:` is the event `seq` (strictly increasing across processes, survives rotation). `Last-Event-ID` resumes after it
  (backup file first); without it only new events are sent, or `?replay=N` (≤200) sends the last N first.
* `?session=<session_id>` and `?types=tool.*,graph.delta` (comma-separated globs) filter server-side.
* `retry: 3000` is sent first and a `: heartbeat` comment every 15 s. At most 8 concurrent streams (`429 too_many_streams`).
  A stream is cancelled when the server shuts down.

Event (`data:` JSON): `seq`, `ts` (UTC), `type`, plus per type:

| `type` | extra fields |
|--------|--------------|
| `tool.start` | `tool`, `trace_id`, `session_id`, `client`, `args_summary` |
| `tool.end` | `tool`, `trace_id`, `session_id`, `dur_ms`, `result_summary` |
| `tool.error` | `tool`, `trace_id`, `session_id`, `dur_ms`, `error` (exception class only), `retryable` (store busy) |
| `tool.shed` | `tool`, `session_id`, `reason` (`circuit_open` \| `congestion`) |
| `session.start`, `session.end` | `session_id`, `client`, `pid`, `proc_start` (`session.start` only: the process creation time, epoch seconds). `session.end` is written when `cognirepo serve` exits cleanly; a killed server writes none |
| `session.client` | `session_id`, `client`, `pid` — written once, when the client's first `tools/list` reveals its name (before any tool call) |
| `watcher.reindex` | `session_id`, `reindexed[]`, `removed[]`, `error` |
| `service` | `service`, `action`, `state`, `ok` |
| `graph.delta` | `graph_seq`, `ops[]` (≤ 200 per event), `part` / `parts` (a batch is split across events sharing one `graph_seq`), `op_count` (whole batch) — or `reset: true` with only `op_count`. See [Graph changes](#graph-changes) |
| `prune` | `dry_run`, `total`, `kept`, `pruned`, `orphans_removed`, `archived`, `dur_ms` — counts only, never memory text. Emitted by every `cognirepo prune` (CLI, scheduled or console). The graph nodes it removes also appear as `graph.delta` events |

Lists are capped at 50 entries (`*_truncated: true`); summaries at 200 chars; fields named like secrets (`token`,
`password`, `api_key`, …) are dropped. Writing never blocks or fails the writer (a held lock for >0.25 s drops the event).
**Privacy:** `args_summary` holds the tool's arguments (e.g. a search query) and free text cannot be scrubbed. Set
`COGNIREPO_EVENTS_METADATA_ONLY=1` to omit `args_summary`/`result_summary`, or `COGNIREPO_EVENTS=0` to write no events.

## Graph changes
The knowledge graph has a monotonic change counter, `graph_seq` (`<store>/graph/graph.seq`, a single integer kept next to —
not inside — `graph.pkl`, so it survives journal compaction and the API reads it without loading the graph). It is
exposed as `indexer.graph_seq` in `GET /api/v1/status`: if it has not moved, the graph has not changed. It is bumped
once per *published batch* of mutations — each journal flush, and each `save()` of ops that were never journaled — and
every bump is described by `graph.delta` events carrying the same number: one event per 200 ops (`part` / `parts`), written
*before* the counter advances, so a reader never sees a number whose parts are still being appended.

`GET /api/v1/graph/changes?since=<seq>&limit=500` returns `{seq, ops, reset, more}`:

* `ops` are the mutations in `(since, seq]`, in order: `add_node {id, kind}`, `del_node {id}` (removes the node's incident
  edges too), `update_node {id}`, `add_edge {src, dst, rel}`, `del_edge {src, dst}`, `update_edge {src, dst}`. Only changes
  that actually happened are described. Pass the returned `seq` as the next `since`.
* `more: true` means the response stopped at `limit` (whole batches only — one batch can exceed it); call again.
* `reset: true` means the feed cannot be proven complete — re-fetch `GET /api/v1/graph`, then continue from `seq`. That
  happens when `since` is ahead of the store (it was rebuilt), more than 100 000 batches behind, or any batch in
  the range is incomplete: an event was dropped or rotated out of the event log, events are disabled
  (`COGNIREPO_EVENTS=0`), or the batch was larger than 5 000 ops (more than one default journal flush), which is
  published as `reset: true` with only an `op_count`. Bulk changes up to that size — most index runs, flushed in batches
  of up to 5 000 ops — **are delivered**, not reset. With `COGNIREPO_EVENTS_METADATA_ONLY=1` node ids are never written
  to the event log, so every batch is a `reset`.
* Completeness is checked, not assumed: every number in `(since, seq]` must have all `parts` of its batch, each exactly
  once and none marked `reset`; a missing or duplicated part answers `reset`. Events without `part`/`parts` (written by
  older versions) are whole batches.
* Cost: about 70 bytes per op in the event log, so a 5 000-op batch is ~350 KB across 25 events. That counts against the
  log's ~10 MiB retention, so a very large index run can push older tool-call history out sooner.
* The deltas describe what *this writer* changed when it made the change durable; they are not a replay of the journal.
  Poll `status.indexer.graph_seq` (cheap) and call `/graph/changes` only when it moved, or follow `graph.delta` on the
  event stream.

## Repos
`GET /api/v1/repos` lists the repos recorded in the global registry `<global dir>/repos.json` (mode 0600; paths and
timestamps only), most recently seen first, plus initialised repos linked to an org or project (`orgs.json`, read-only)
and the repo this server was started for. Entries are added or touched — best-effort, throttled to once a minute per
repo, and only for initialised repos — by `init`, `index-repo`, every watcher registration, **and by `cognirepo serve`,
`ui`, `doctor` and `prime`**, so a repo an agent merely uses shows up. `COGNIREPO_REPO_REGISTRY=0` turns it off.
Repos that never ran any of those can be added explicitly: `cognirepo repos add <path>`, or
`cognirepo repos scan --root DIR [--depth 3] [--dry-run]` (opt-in; looks for `.cognirepo/config.json`, skips hidden and
junk directories, does not follow symlinks, visits at most 20 000 directories). Nothing scans by default.

Each entry: `name`, `root`, `store`, `exists` (repo directory still on disk), `first_seen`, `last_seen`, `indexed`,
`indexed_at`, `git_commit`, `watcher` (`state` running\|stale\|stopped, `pid`, `heartbeat_age_s`, `last_reindex`),
`hooks_installed` (git `post-commit` has a cognirepo block) and `auto_index` (`watch.auto_enabled`, default true).

The listing is strictly read-only: it never creates directories or deletes stale pid files in the repos it lists.

### Reading another repo: `?repo=`
`status`, `graph`, `graph/changes`, `harness`, `insights`, `insights/report`, `events`, `processes`, `sessions` and
`sessions/{id}` accept `repo=<path or name>` (a name is the repo directory's name from `/repos`). It is resolved **only**
against the registry, org links and the served repo — a request can never name an arbitrary filesystem path, so
`?repo=/etc` is just `404 unknown_repo`. Errors: `404 unknown_repo`, `409 ambiguous_repo` (two repos share a name — use
the path), `404 repo_missing` (directory gone), `404 repo_not_initialised` (no store). Omitted = the served repo, as before.

Everything that acts or reports live state stays bound to the served repo: `services` (list, start, stop) and
`settings/auto-index` answer `409 not_served_repo` for any other repo, and the attempt is audited
(`..._denied_repo`). For another repo, `status.daemon` is read without touching its pid files, `processes` omits the `ui`
row (this server is not that repo's), and `graph` keeps at most two graphs in memory (the served one plus one more,
dropped after 2 minutes idle). Reading another repo's store uses the same token and the same trust as reading the served one.

## Sessions
`GET /api/v1/sessions` and `/api/v1/sessions/{session_id}` are derived from the same event log — no second store, so they
need no extra writer and share its privacy switches. One session = one `cognirepo serve` process.

* `client` is the MCP `initialize` handshake's `clientInfo.name` (`claude-code`, …). It is only readable while a request
  is being handled, so the server captures it at the client's first `tools/list` — which clients send right after
  `initialize` — and records a `session.client` event; it is `null` only in the moments before that (or if the SDK does not
  expose the handler, in which case it falls back to the first tool call).
* `state`: `closed` (a `session.end` was seen, **or its process is gone**), `active` (last event ≤ 10 min ago) or `stale`
  (quiet longer — idle). `closed_by` says why a session is closed: `session_end` or `process_gone`. A killed server is
  detected from the `pid` and `proc_start` recorded at `session.start`: the pid is dead, or alive with a different
  creation time (a reused pid), so a SIGKILLed server no longer shows as `stale`. Sessions recorded before pids were
  kept keep the old rules.
* `call_count` counts `tool.start` plus `tool.shed`. In `/sessions/{session_id}`, each call joins `tool.start` to its
  `tool.end`/`tool.error` by `trace_id`; `status` is `running` | `ok` | `error` | `shed`, and `result_summary` carries the
  error class or shed reason when there is no result.
* **Retention:** the *calls* of a session are whatever the event log still holds (live file plus one backup, ~10 MiB).
  The sessions themselves outlive that: `<store>/events/sessions.json` keeps the newest 200 sessions' start, client, pid and
  final `call_count`. It is written only when a session starts, learns its client, or ends — never per tool call — under
  the events lock, and is merged with the log (the larger `call_count` wins). A session that was killed has no final
  count, so after rotation its `call_count` is whatever the log still shows. Nothing is written with
  `COGNIREPO_EVENTS=0`. With `COGNIREPO_EVENTS_METADATA_ONLY=1` the `args_summary`/`result_summary` fields are absent.

## Security model
| Threat | Mitigation |
|--------|------------|
| A web page calls `127.0.0.1` (CSRF) | Exact `Origin` allowlist (own origin only; extra origins only via explicit `--allow-origin`, never `*`), `SameSite=Strict` cookie, token required |
| DNS rebinding | Exact `Host` allowlist (`127.0.0.1:PORT`, `localhost:PORT`, `[::1]:PORT`) |
| Token guessing | 5 bad tokens ⇒ lockout with exponential backoff (5 s … 5 min); a locked client is refused even with the right token |
| Exposure on the network | Binds loopback only. A non-loopback `--host` (incl. `0.0.0.0`) is refused unless `--unsafe-bind` is given, with a loud warning. Autostart can never contain `--unsafe-bind` |
| XSS in the page | `Content-Security-Policy: default-src 'self'`, `nosniff`, `X-Frame-Options: DENY`, `no-store` |
| Control abuse | Allowlist, strict `confirm`, local audit log of every attempt (including denials) at `<global dir>/ui/audit.log` (0600, rotated, never contains the token) |
| Arbitrary file read / exec | No such endpoint exists; the graph/harness/status handlers read fixed files only |

The UI process is **read-only** with respect to the index: it never imports `ASTIndexer` or `LocalVectorDB`
(their load paths can rename live index files under a concurrent writer) and never calls `KnowledgeGraph.save()`.

**Remote viewing is out of scope** (no relay, no hosted component, no password login). A Tailscale recipe will be
documented separately; until then keep the server on loopback.

## Autostart (opt-in)
First interactive run asks `Start the console automatically at login? (y/N)` (default **No**, asked once, never in
scripts). `cognirepo ui --autostart on|off` does it explicitly; both are idempotent.
| OS | Mechanism |
|----|-----------|
| Linux | `~/.config/systemd/user/cognirepo-ui.service` (`systemctl --user enable --now`) |
| macOS | `~/Library/LaunchAgents/com.cognirepo.ui.plist` (`launchctl bootstrap gui/<uid>`) |
| Windows | Task Scheduler task `CogniRepoUI` (logon trigger, current user, least privilege) |

The installed command is `<this python> -m interface.cli.main ui --serve --no-open --host 127.0.0.1` — loopback by
construction, and independent of whatever `cognirepo` happens to be first on `PATH`.

## Console package contract (`cognirepo-console` pip package)
`import cognirepo_console` must expose `STATIC_DIR` (a directory containing `index.html`); the server mounts it at `/`.
The console must perform the fragment→cookie swap itself (or include `/_cognirepo/bootstrap.js`) and call only the
endpoints above.

## Files (under `<global dir>/ui/`, default `~/.cognirepo/ui/`)
`session.json` (token/port/pid, 0600) · `audit.log` (+ `.1`) · `server.log` · `config.json` (autostart choice).
