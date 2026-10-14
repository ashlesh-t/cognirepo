# ADR 003 — Per-user daemon (`cognirepod`): measured case, shape, phasing

- **Status:** Proposed (tracked in #116; #117 depends on it)
- **Related:** ADR 001 (single writer), ADR 002 (SQLite graph), #117 (bounded queue), #146/#148 (watcher),
  #129 (control API), `docs/RESOURCES.md`

## Context

Every agent session starts its own `cognirepo serve` (MCP over stdio). Each one loads its own graph,
AST index, FAISS index and embedder, so memory grows linearly with the number of sessions, and the
processes contend for the same files (the reason ADR 001 and the integrity epic exist). #116 proposes
one per-user daemon that owns all of that and turns `serve` into a thin proxy.

Before building a second process model we measured whether the premise holds, because
`docs/RESOURCES.md` currently says a `serve` process is ~220 MB idle and the idle manager already
evicts the model, graph and indexer after `idle_ttl_seconds` (default 600 s).

## Measurement (`scripts/measure_serve_footprint.py`)

N real `cognirepo serve` processes against one repo (this repo; `.cognirepo/` = 190 MB, ~3.7k
symbols), each driven by a real MCP client: connect, then `get_session_brief` + 2× `context_pack`.
Linux, Python 3.14, one machine, `COGNIREPO_NO_WATCHER=1`. RSS is per-process resident memory; PSS
divides shared pages between processes, so the PSS **sum** is the honest total.

| Sessions | after connect: RSS sum / PSS sum | after tool calls: RSS sum / PSS sum | per process (active) |
|---:|---:|---:|---:|
| 1 | 434 / 404 MB | 671 / 642 MB | 671 MB |
| 3 | 1,291 / 1,141 MB | 2,016 / 1,821 MB | ~672 MB |
| 5 | 2,175 / 1,898 MB | 3,395 / 3,028 MB | ~679 MB |

Findings:

1. **Cost is linear and little is shared.** PSS is only ~10 % below RSS: the OS shares the shared
   libraries, not the graph, index or model. Five agents on one repo is **~3 GB**.
2. **The ~220 MB "idle" figure in RESOURCES.md is not what a connected, used session costs**: 430 MB
   right after connect, ~670 MB once it has answered a few queries. (It is plausible that figure was taken
   on a smaller repo or before the model was loaded; this ADR's PR corrects the doc.)
3. Where the 430 MB baseline goes: bare interpreter 13 MB; `mcp` 65 MB; `faiss` 44 MB; `numpy` +
   `networkx` 50 MB; `fastembed` 93 MB; `import interface.server.mcp_server` alone is **148 MB**; the
   other ~280 MB is state loaded on connect/first call. So roughly a third is import weight that a thin
   proxy would not carry, and two thirds is per-repo state that a daemon would hold once.
4. Idle eviction only helps *idle* sessions. The case that hurts is several agents working at once on one
   repo — exactly the multi-terminal use that prompted #116.

So the premise holds for the concurrent case, and it is not a rounding error.

## Decision

Build `cognirepod` as an **opt-in, per-user, local-only** process; keep today's in-process `serve` as
the fallback so nothing becomes unavailable if the daemon is absent.

1. **Transport.** A Unix domain socket at `$XDG_RUNTIME_DIR/cognirepo/daemon.sock` (fallback
   `~/.cognirepo/run/daemon.sock`), mode `0600`, peer uid checked with `SO_PEERCRED`. No TCP. (Windows:
   a named pipe with a user-only ACL, as a later phase; the control API in #129 is the only TCP
   listener and stays separate.)
2. **Protocol.** Length-prefixed JSON-RPC 2.0, reusing the MCP tool names and argument/return shapes, plus
   one required field: the repo root. `serve` forwards `tools/call` unchanged, so there is a single
   implementation of every tool (`interface/tools/*`), reached in-process or through the daemon.
3. **Per-repo context.** The daemon holds an LRU of `RepoContext` objects (graph, AST index, vector DB,
   watcher), keyed by repo root. The path layer is already request-scoped (`core.config.paths._CTX_DIR`
   ContextVar, used by `_repo_ctx`), which is what makes several repos in one process feasible; what
   is *not* ready is the module-level singletons in `mcp_server` (`_get_graph`, `_get_indexer`), which are
   per process and must become per-`RepoContext`. Contexts are evicted after idle (reusing
   `interface/server/idle_manager.py`); the **embedder is shared across repos**.
4. **Single writer.** All mutations for a repo go through one in-process bounded FIFO (#117) consumed by one
   worker. This replaces cross-process lock contention for daemon clients; `store_lock()` and the writer
   lease stay in force for non-daemon processes (the CLI, `index-repo`, a `serve` running in fallback mode)
   until nothing else writes (ADR 001, step 7).
5. **Lifecycle.** First client that finds no daemon takes a startup lock and spawns it detached (the same
   fork-free spawn as the watcher, `core/config/procutil.detach_kwargs`). The daemon exits after
   `daemon.idle_exit_secs` with no clients and no contexts. A version handshake on connect restarts a daemon
   older than the client. `cognirepo daemon start|stop|status`; `doctor` reports it.
6. **Watchers.** The daemon owns one watcher per *registered* repo through the existing per-repo lease, so the
   `serve`-embedded watcher thread and the standalone watcher both become "ask the daemon". Catch-up on
   start (#146) already covers daemon restarts.
7. **Failure model.** A daemon crash drops in-flight requests; clients retry once, then fall back to
   in-process. No data is at risk beyond what ADR 001 already allows (writes are atomic or transactional).
   A client never blocks on a wedged daemon: connect and request timeouts, then fallback.

## Alternatives considered

- **Do nothing; lower `idle_ttl_seconds`.** Cheap, helps idle sessions, does nothing for concurrent ones (the
  measured case). Worth doing anyway; not a substitute.
- **Slim the per-process baseline (lazy imports, mmap FAISS, SQLite graph #115).** Attacks the same
  linear cost per process. It could remove perhaps the import third and, with #115, much of the state third,
  and it is independent of the daemon. It does not remove duplicated *work* (N embedders warming, N
  watchers' catch-ups) or the cross-process write contention. Do it first where cheap: it also shrinks the
  daemon. The daemon is justified by single-writer ordering + shared embedder, not by RSS alone.
- **A shared-memory model.** Complex, platform-specific, fragile with pickled/NetworkX state. Rejected.
- **One daemon per repo.** Keeps isolation but multiplies processes again. Rejected; per-repo isolation is
  the `RepoContext`.

## Consequences

- Concurrent-agent cost goes from ~N × 0.67 GB to ~one context (≈0.7 GB) + N thin proxies (≈65 MB each is the
  import floor; less with lazy imports). Five sessions: ~3.0 GB → ~1.0 GB on this repo (estimate, to be
  re-measured in phase 3).
- A new long-lived process to supervise, version and secure. It runs as the user, local-only, and is optional.
- `serve` must keep working without it; tests run both modes.
- Debuggability: two hops instead of one. Mitigated by request ids in logs and `daemon status`.

## Delivery plan (separate PRs)

1. **`RepoContext`** — replace the `mcp_server` module-level singletons with an in-process per-repo object
   (behaviour-neutral; `serve` makes one). The prerequisite for multi-repo; independently reviewable.
2. **Daemon skeleton** — socket server, protocol, handshake, `daemon start|stop|status`, `doctor` check.
   No tool traffic yet.
3. **Proxy mode** — `serve` forwards to the daemon behind `daemon.enabled: false` (opt-in), with fallback;
   re-run `scripts/measure_serve_footprint.py` and record the result here.
4. **Write queue** (#117) and **watcher pool**.
5. Flip the default only after a soak with no regression and a published measurement.

Cheap wins to schedule alongside (not blocked on any of the above): lazy-import the embedder and Chroma in
`serve`, and correct the ~220 MB figure in `docs/RESOURCES.md`.

## Open questions

1. Is a ~1 GB floor for five agents good enough to justify the new process, or should the slimming work
   (lazy imports, #115) land first and the spike be repeated? (Recommendation: slimming first where it is
   cheap, then re-measure; the daemon is still needed for single-writer ordering.)
2. Auto-spawn by the first client (convenient) vs. explicit `cognirepo daemon start` / autostart service
   (predictable). Recommendation: auto-spawn only when `daemon.enabled` is true.
3. Windows named-pipe parity in the first release, or Linux/macOS first.
