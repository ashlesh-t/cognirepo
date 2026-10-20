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


class ServiceState(BaseModel):
    name: str
    state: str
    pid: int | None = None
    port: int | None = None
    changed: bool | None = None
    reason: str | None = None     # set when state == "failed": a machine-readable cause
    detail: str | None = None
    progress: IndexProgress | None = None   # index service while running
    last_run: IndexRun | None = None        # index service after a run


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
