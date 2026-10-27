# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Response models for ``/api/v1``. These ARE the contract the console consumes: additive changes only."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class ErrorBody(BaseModel):
    error: str


class OkBody(BaseModel):
    ok: bool


class RepoInfo(BaseModel):
    root: str
    name: str


class DaemonStatus(BaseModel):
    state: Literal["running", "stale", "stopped"]
    pid: int | None = None
    name: str | None = None
    heartbeat_age_s: float | None = None


class McpStatus(BaseModel):
    transport: str
    tool_count: int
    tools: list[str]
    manifest_available: bool


class IndexerStatus(BaseModel):
    indexed: bool
    indexed_at: str | None = None
    git_commit: str | None = None
    ast_index_bytes: int | None = None
    last_watcher_reindex: dict[str, Any] | None = None
    graph_seq: int = 0            # knowledge-graph change counter: compare it to detect any graph change
    graph_base_incomplete: bool = False   # watcher refused its last graph save: run one full index-repo
    auto_index: bool = True               # config watch.auto_enabled (absent = on)
    store_bytes: dict[str, int] = {}      # bytes per top-level store directory, "_files" (loose files), "total"
    watch_queue: dict[str, Any] | None = None   # watcher queue state (depth, max, oldest_age_s, overflows, ...); null if no watcher


class UiInfo(BaseModel):
    pid: int
    started_at: str


class StatusResponse(BaseModel):
    api_version: str
    version: str
    repo: RepoInfo
    daemon: DaemonStatus
    mcp: McpStatus
    indexer: IndexerStatus
    ui: UiInfo


class GraphStats(BaseModel):
    nodes: int
    edges: int


class GraphNode(BaseModel):
    id: str
    type: str | None = None
    file: str | None = None
    line: int | str | None = None
    unresolved: bool | None = None
    ambiguous: bool | None = None
    dispatch: str | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    rel: str | None = None
    weight: float | None = None


class GraphResponse(BaseModel):
    stats: GraphStats
    root: str | None = None
    found: bool
    truncated: bool
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class HarnessServer(BaseModel):
    name: str
    command: str


class HarnessConfig(BaseModel):
    label: str
    readable: bool
    servers: list[HarnessServer]


class HarnessClient(BaseModel):
    client: str
    registered: bool
    configs: list[HarnessConfig]


class LastContext(BaseModel):
    generated_at: str | None = None
    tool: str | None = None
    repo: str | None = None
    section_count: int


class InsightsInfo(BaseModel):
    exists: bool
    generated_at: str | None = None
    bytes: int = 0


class HarnessResponse(BaseModel):
    clients: list[HarnessClient]
    last_context: LastContext | None = None


class IndexProgress(BaseModel):
    done: int
    total: int


class IndexRun(BaseModel):
    """Outcome of the last ``index`` service run (kept in the UI server's memory)."""
    result: str                   # ok | busy | failed
    reason: str | None = None     # store_busy | base_incomplete | index_failed
    exit_code: int | None = None  # null when the run was started by a previous UI server (not our child)
    retryable: bool = False       # true for busy: another writer held the store, retry in a moment
    finished_at: str
    duration_s: float
    detail: str | None = None


class PruneAuto(BaseModel):
    """Scheduled prune settings (``prune.*`` in config.json); the scheduler is opt-in."""
    enabled: bool
    every_hours: int
    archive: bool                 # scheduled runs archive instead of deleting (default true)
    next_due_in_s: int | None = None


class ServiceState(BaseModel):
    name: str
    state: str
    pid: int | None = None
    port: int | None = None
    changed: bool | None = None
    reason: str | None = None     # set when state == "failed": a machine-readable cause
    detail: str | None = None
    progress: IndexProgress | None = None   # index service while running
    last_run: IndexRun | None = None        # index / prune service after a run
    summary: dict[str, Any] | None = None   # prune: counts of the last run, or (dry run) what would be pruned
    auto: PruneAuto | None = None           # prune: the scheduled-run settings
    dry_run_fresh: bool | None = None       # prune: a real run is allowed (a dry run completed < 30 min ago)
    dry_run: bool | None = None             # true when this response is a dry-run report
    retryable: bool | None = None


class GraphFile(BaseModel):
    """One backend's graph file(s): ``graph.pkl`` for networkx, ``graph.sqlite`` (+ WAL) for sqlite."""
    exists: bool
    bytes: int
    mtime: float | None = None


class GraphRecommendation(BaseModel):
    """Which backend to prefer and why. Rough guidance from one benchmark, not a rule."""
    use: str
    confidence: str          # clear | leaning | either
    reasons: list[str]


class GraphMigrateProgress(BaseModel):
    phase: str
    done: int = 0
    total: int = 0


class GraphJob(BaseModel):
    """The detached ``graph migrate`` run (idle until one has been started)."""
    state: str               # idle | running
    last_run: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    progress: GraphMigrateProgress | None = None


class GraphBackendState(BaseModel):
    """Which graph store is in force, what each file holds, whether switching is safe, and what to recommend."""
    active: str
    configured: str
    env_override: str | None = None
    forced_by_encryption: bool
    note: str | None = None
    files: dict[str, GraphFile]
    nodes: int | None = None
    edges: int | None = None
    stale_note: str | None = None
    recommendation: GraphRecommendation
    sessions: int
    can_toggle: bool
    toggle_blocker: str | None = None
    switch_to: str
    switch_needs_migration: bool
    job: GraphJob | None = None


class GraphSwitchResult(BaseModel):
    action: str              # noop | switched | migrating
    state: GraphBackendState


class AutoIndexState(BaseModel):
    auto_index: bool
    changed: bool


class SessionInfo(BaseModel):
    id: str
    client: str | None = None     # MCP clientInfo.name; null until the session's first tool call
    started: str
    last_activity: str
    call_count: int
    closed_at: str | None = None
    state: Literal["active", "stale", "closed"]
    pid: int | None = None        # the MCP server process (from session.start); null for older sessions
    closed_by: Literal["session_end", "process_gone"] | None = None   # why state is "closed"


class ProcessInfo(BaseModel):
    role: Literal["ui", "watcher", "mcp"]
    pid: int
    state: str                    # running | stale | stopped (watcher) / active | stale (mcp)
    rss_bytes: int | None = None
    threads: int | None = None
    heartbeat_age_s: float | None = None   # watcher only
    detail: str | None = None     # mcp: client name
    session_id: str | None = None # mcp only


class SessionCall(BaseModel):
    trace_id: str | None = None
    tool: str | None = None
    started: str
    dur_ms: int | None = None
    status: Literal["running", "ok", "error", "shed"]
    args_summary: str | None = None
    result_summary: str | None = None


class SessionDetail(SessionInfo):
    calls: list[SessionCall]


class RepoWatcher(BaseModel):
    state: Literal["running", "stale", "stopped"]
    pid: int | None = None
    heartbeat_age_s: float | None = None
    last_reindex: dict[str, Any] | None = None


class RepoDaemon(BaseModel):
    """The daemon repo worker serving this repo (null when the daemon is not running or not serving it)."""
    pid: int | None = None
    alive: bool | None = None
    unresponsive: bool | None = None
    clients: int | None = None      # connected agent sessions
    calls: int | None = None
    rss_bytes: int | None = None
    idle_secs: float | None = None


class RepoEntry(BaseModel):
    name: str
    root: str
    store: str
    exists: bool                  # the repo directory is still on disk
    first_seen: str | None = None
    last_seen: str | None = None
    indexed: bool
    indexed_at: str | None = None
    git_commit: str | None = None
    watcher: RepoWatcher
    hooks_installed: bool
    auto_index: bool
    daemon: RepoDaemon | None = None


class GraphOp(BaseModel):
    op: Literal["add_node", "del_node", "update_node", "add_edge", "del_edge", "update_edge"]
    id: str | None = None         # node ops
    kind: str | None = None       # add_node: the node type
    src: str | None = None        # edge ops
    dst: str | None = None
    rel: str | None = None        # add_edge: the relation


class GraphChanges(BaseModel):
    seq: int                      # the graph_seq the returned ops bring a client up to; pass it as `since` next
    ops: list[GraphOp]
    reset: bool                   # true: re-fetch GET /api/v1/graph, then continue from `seq`
    more: bool = False            # true: stopped at `limit`; call again with since=seq


class DaemonWorker(BaseModel):
    repo: str
    pid: int
    alive: bool
    unresponsive: bool = False
    clients: int | None = None
    calls: int | None = None
    rss_bytes: int | None = None
    idle_secs: float | None = None
    started: float | None = None
    served: bool = False            # the repo this UI server was started for


class CognirepodStatus(BaseModel):
    supported: bool                 # this platform has Unix sockets (POSIX); false on Windows
    enabled: bool                   # daemon.enabled / COGNIREPO_DAEMON
    running: bool
    version: str | None = None
    pid: int | None = None
    rss_bytes: int | None = None
    socket: str | None = None
    max_workers: int | None = None
    started: float | None = None
    workers: list[DaemonWorker] = []


class QueueState(BaseModel):
    """The file watcher's queue for the selected repo (``running: false`` when no watcher is running)."""
    running: bool
    depth: int | None = None
    max: int | None = None
    oldest_age_s: float | None = None
    enqueued: int | None = None
    coalesced: int | None = None
    dropped: int | None = None
    overflows: int | None = None
    batches: int | None = None
    files: int | None = None
    max_depth: int | None = None
    last_batch: dict[str, Any] | None = None
    batch_max: int | None = None
    debounce_ms: int | None = None
    pid: int | None = None
    updated_at: str | None = None
