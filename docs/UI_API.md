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
| `GET` | `/api/v1/services` | State of the allowlisted services |
| `POST` | `/api/v1/services/{name}/start` | Start a service. Body must be `{"confirm": true}` (strict boolean) |
| `POST` | `/api/v1/services/{name}/stop` | Stop a service. Body must be `{"confirm": true}` |
| `POST` | `/api/v1/settings/auto-index` | Persist `watch.auto_enabled` for this repo. Body `{"enabled": bool, "confirm": true}`. See [Index and hooks](#index-and-hooks-services) |

**Service allowlist:** `watcher` (the repo's file-watcher daemon), `index` and `hooks` (see
[Index and hooks](#index-and-hooks-services)), `insights` (`start` regenerates the report by running `cognirepo insights`; one run at a time, `stop` is `409 not_stoppable`) and `metrics` (in-process Prometheus
`/metrics` on `127.0.0.1:9090`). Any other name is a `404` before anything else is evaluated. Each service
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

`index` also reports `progress` (`{done, total}` files, while running) and `last_run` (kept in the UI server's memory,
cleared when a new run starts): `{result, reason, exit_code, retryable, finished_at, duration_s, detail}`.
- `result: "busy"` / `reason: "store_busy"` / `retryable: true` — another writer holds the store (CLI exit 75, or an
  indexer holding the graph writer lease). This is not an error; retry in a moment.
- `result: "failed"` / `reason: "base_incomplete"` — there is no complete base graph, so an incremental run refuses to
  replace it with a fragment (COGNIREPO-122). Run one full `cognirepo index-repo .`.
- `result: "failed"` / `reason: "index_failed"` — anything else; `detail` is the tail of the output (for example the
  repo is not a git repo or has no commits, which `--changed-only` needs).

`GET /status` → `indexer` adds `graph_base_incomplete` (the watcher's latest batch skipped its graph save for the same
reason; `last_watcher_reindex.graph_skipped` carries the text; false until a batch has run) and `auto_index`
(`watch.auto_enabled`, default true). `last_watcher_reindex` (`timestamp`, `reindexed[]`, `removed[]`, `error`) is
there too.

`POST /api/v1/settings/auto-index` writes only `watch.auto_enabled` into `<store>/config.json` (read-modify-write under
the store lock, atomic replace; every other key is untouched) and answers `{auto_index, changed}`; `409 not_initialised`
without a `config.json`. When `cognirepo ui` starts and the setting is **explicitly `true`**, it starts the repo's watcher
(best-effort, off the request path, audited as `auto_index_start`). Absent — the default, which the MCP server treats as
on — does nothing at UI start.

### Status codes
`200` ok · `400` `confirm_required` · `401` missing/invalid token · `403` bad `Host`/`Origin` · `404` unknown service/path ·
`409` `port_in_use` · `422` invalid parameters · `429` locked out (`Retry-After` seconds) · `501` unsupported platform.

### Stability
`/api/v1` is additive-only: fields may be added, never removed or retyped. A breaking change ships as `/api/v2`.

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
| `session.start`, `session.end` | `session_id`, `client`, `pid` (`session.end` is written when `cognirepo serve` exits cleanly; a killed server writes none) |
| `watcher.reindex` | `session_id`, `reindexed[]`, `removed[]`, `error` |
| `service` | `service`, `action`, `state`, `ok` |
| `graph.delta` | `graph_seq`, `ops[]` (see [Graph changes](#graph-changes)) or `reset: true`, `op_count` |
| `prune` | reserved (#213) |

Lists are capped at 50 entries (`*_truncated: true`); summaries at 200 chars; fields named like secrets (`token`,
`password`, `api_key`, …) are dropped. Writing never blocks or fails the writer (a held lock for >0.25 s drops the event).
**Privacy:** `args_summary` holds the tool's arguments (e.g. a search query) and free text cannot be scrubbed. Set
`COGNIREPO_EVENTS_METADATA_ONLY=1` to omit `args_summary`/`result_summary`, or `COGNIREPO_EVENTS=0` to write no events.

## Graph changes
The knowledge graph has a monotonic change counter, `graph_seq` (`<store>/graph/graph.seq`, a single integer kept next to —
not inside — `graph.pkl`, so it survives journal compaction and the API reads it without loading the graph). It is
exposed as `indexer.graph_seq` in `GET /api/v1/status`: if it has not moved, the graph has not changed. It is bumped
once per *published batch* of mutations — each journal flush, and each `save()` of ops that were never journaled — and
every bump emits one `graph.delta` event carrying the same number.

`GET /api/v1/graph/changes?since=<seq>&limit=500` returns `{seq, ops, reset, more}`:

* `ops` are the mutations in `(since, seq]`, in order: `add_node {id, kind}`, `del_node {id}` (removes the node's incident
  edges too), `update_node {id}`, `add_edge {src, dst, rel}`, `del_edge {src, dst}`, `update_edge {src, dst}`. Only changes
  that actually happened are described. Pass the returned `seq` as the next `since`.
* `more: true` means the response stopped at `limit` (whole batches only — one batch can exceed it); call again.
* `reset: true` means the feed cannot be proven complete — re-fetch `GET /api/v1/graph`, then continue from `seq`. That
  happens when `since` is ahead of the store (it was rebuilt), more than 100 000 batches behind, or any batch in
  the range is missing: its event was dropped or rotated out of the event log, events are disabled
  (`COGNIREPO_EVENTS=0`), or the batch was a bulk change (> 200 ops, e.g. an index run) which is published as
  `reset: true` with only an `op_count`. With `COGNIREPO_EVENTS_METADATA_ONLY=1` node ids are never written to the event
  log, so every batch is a `reset`.
* Completeness is checked, not assumed: every number in `(since, seq]` must have exactly one non-reset `graph.delta`.
* The deltas describe what *this writer* changed when it made the change durable; they are not a replay of the journal.
  Poll `status.indexer.graph_seq` (cheap) and call `/graph/changes` only when it moved, or follow `graph.delta` on the
  event stream.

## Repos
`GET /api/v1/repos` lists the repos recorded in the global registry `<global dir>/repos.json` (mode 0600; paths and
timestamps only), most recently seen first, plus the repo this server was started for. `init`, `index-repo` and every
watcher registration (`watch`, `serve`'s embedded watcher) add or touch an entry — best-effort and throttled to once a
minute per repo; `COGNIREPO_REPO_REGISTRY=0` turns it off.

Each entry: `name`, `root`, `store`, `exists` (repo directory still on disk), `first_seen`, `last_seen`, `indexed`,
`indexed_at`, `git_commit`, `watcher` (`state` running\|stale\|stopped, `pid`, `heartbeat_age_s`, `last_reindex`),
`hooks_installed` (git `post-commit` has a cognirepo block) and `auto_index` (`watch.auto_enabled`, default true).

The listing is strictly read-only: it never creates directories or deletes stale pid files in the repos it lists.
Repos indexed before this existed appear after their next `init`/`index-repo`/`watch`. There is no `?repo=` selector on
the other endpoints yet — `cognirepo ui` still serves one repo per server (see #116).

## Sessions
`GET /api/v1/sessions` and `/api/v1/sessions/{session_id}` are derived from the same event log — no second store, so they
need no extra writer and share its privacy switches. One session = one `cognirepo serve` process.

* `client` is the MCP `initialize` handshake's `clientInfo.name` (`claude-code`, …). It can only be read while a
  request is being handled, so it is `null` until the session's first tool call.
* `state`: `closed` (a `session.end` was seen), `active` (last event ≤ 10 min ago) or `stale` (no `session.end`
  and quiet longer — idle, or the server was killed).
* `call_count` counts `tool.start` plus `tool.shed`. In `/sessions/{session_id}`, each call joins `tool.start` to its
  `tool.end`/`tool.error` by `trace_id`; `status` is `running` | `ok` | `error` | `shed`, and `result_summary` carries the
  error class or shed reason when there is no result.
* **Retention:** history is whatever the event log still holds (the live file plus one backup, ~10 MiB); older sessions
  disappear. With `COGNIREPO_EVENTS_METADATA_ONLY=1` the `args_summary`/`result_summary` fields are absent.

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
