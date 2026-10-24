# The per-user daemon (`cognirepod`) — opt-in

Every agent session normally starts its own `cognirepo serve`, and each one loads its own graph, AST index and
embedder: five agents on one repo cost five times the memory (`docs/RESOURCES.md`) and contend on the same files.
The daemon lets them share **one** loaded copy. It is **off by default**, local-only, and `serve` keeps working exactly as
before when it is absent.

## How it works

```
 agent ── stdio MCP ──► cognirepo serve (thin proxy, ~70 MB) ──┐
 agent ── stdio MCP ──► cognirepo serve (thin proxy)           ├─► repo worker for /path/to/repo (loaded once)
 agent ── stdio MCP ──► cognirepo serve (thin proxy)           ┘        ▲
                                                                        │ started / reaped by
                                                                  cognirepod (supervisor)
```

- **Supervisor** (`cognirepod`): owns `daemon.sock`, starts a repo worker on demand, keeps at most `daemon.max_workers`,
  exits after `daemon.idle_exit_secs` with nothing to do. It is **not** in the data path: a client asks it "where is the
  worker for this repo?" and then talks to the worker directly.
- **Repo worker**: the normal server code with one repo fixed (its graph, index, vector store, lease-based watcher, prune
  scheduler), serving many agents over its own socket. Each connected agent gets its own session id, client name and call
  count, so `/api/v1/sessions` still shows one row per agent. A worker exits after `daemon.worker_idle_secs` with no agent.
- **Thin proxy**: `cognirepo serve` with the daemon enabled. It speaks stdio MCP to the agent and forwards `tools/list` and
  `tools/call`; it imports only the MCP SDK (not faiss, numpy, fastembed or the tool modules).

Why a worker per repo rather than one process holding every repo (as ADR 003 first proposed): the server code has ~10
module-level caches and 38 tools that assume one repo per process. A worker per repo reuses that code unchanged, so the
daemon cannot leak one repo's state into another.

## Turning it on

```bash
export COGNIREPO_DAEMON=1              # or: "daemon": {"enabled": true} in ~/.cognirepo/config.json
cognirepo daemon status                # started by the first `cognirepo serve`; or: cognirepo daemon start
```

The repo must be initialised (`cognirepo init`). Anything else — an uninitialised directory, no Unix sockets (Windows),
a run directory that cannot be created, a daemon that does not answer within its timeouts — makes `serve` run in-process
as usual. `cognirepo doctor` reports the daemon.

## Security

Local only, no TCP. The run directory (`$COGNIREPO_RUN_DIR`, else `$XDG_RUNTIME_DIR/cognirepo`, else
`~/.cognirepo/run`) is created `0700` and refused if it belongs to someone else; sockets are `0600`; the peer's uid is
checked where the OS reports it (`SO_PEERCRED` on Linux, `LOCAL_PEERCRED` on macOS). Frames are capped at 8 MiB. The
supervisor only starts a worker for a repo that exists **and has a CogniRepo store** — a request cannot name an arbitrary
path — and only the tools registered in the server are callable. The daemon runs as you and has the same access `serve` has.

## Failure behaviour

| Situation | What happens |
|---|---|
| Daemon not running / cannot start | `serve` runs in-process |
| Daemon too slow to answer | treated as absent after `daemon.connect_timeout_secs` |
| Worker died **between** calls | the proxy notices the closed socket and reconnects; nothing was sent, so nothing runs twice |
| Worker died **during** a call | the agent gets an error saying the call may or may not have been applied; the next call reconnects. A tool is never silently re-run |
| Older daemon / worker after an upgrade | replaced on the next connect (version handshake) |
| More active repos than `daemon.max_workers` | an idle worker is replaced; if every worker has agents, the new session runs in-process |

## Memory

`scripts/measure_serve_footprint.py --repo R -n 5 [--daemon]` measures real MCP sessions. On this repo (a 190 MB
`.cognirepo/`, Linux, Python 3.14, `fastembed` not installed so no embedding model is loaded in either mode):

| 5 agents | processes | RSS | PSS |
|---|---|---|---|
| in-process `serve` | 5 × ~345 MB | 1,726 MB | 1,526 MB |
| daemon, right after the calls | 5 proxies × 72 MB + supervisor 31 MB + worker 955 MB | 1,346 MB | 1,205 MB |
| daemon, a few seconds later | 5 × 72 + 31 + worker 393 MB | **783 MB** | **642 MB** |

The worker trims freed memory (`gc.collect()` + `malloc_trim`) once it has been quiet for 3 s: after failed tool calls
it held hundreds of MB of cyclic garbage. The saving grows with the size of the loaded state and with the embedding
model, which a worker loads once instead of once per agent (not measured here).

## Limits

- POSIX only for now (Linux, macOS). On Windows `daemon.enabled` is ignored.
- A repo worker does not share the embedder with other repos' workers.
- Write ordering **between processes** still relies on the store lock; the single-writer queue (#117) builds on this.
- The thin proxy adds one local round trip per call (sub-millisecond on a Unix socket).
