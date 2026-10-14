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


class ServiceState(BaseModel):
    name: str
    state: str
    pid: int | None = None
    port: int | None = None
    changed: bool | None = None
