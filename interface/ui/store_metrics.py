# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Prometheus collector that derives its numbers from a repo's store, not from process memory (#212).

The MCP server, the watcher and the metrics server are different processes, so counters registered
inside one of them are invisible to the others. This collector instead reads what every process
already leaves on disk — ``events/events.jsonl`` and a few small files — on each scrape. No
``PROMETHEUS_MULTIPROC_DIR``, no extra writes by the hot paths, nothing to clean up.

* **Tool calls** (``cognirepo_tool_calls_total``, ``cognirepo_tool_call_duration_seconds``,
  ``cognirepo_store_busy_total``) come from ``tool.*`` events. The collector reads the retained event
  log on its first scrape and only new events after that, so the counters are monotonic for the life of
  the metrics server (a restart is an ordinary Prometheus counter reset). The retained window is the live
  file plus one backup (~10 MiB), so the first scrape may start from a partial history.
* **Gauges** come from the store: ``graph/graph.seq`` and ``graph/graph.stats``, ``index/manifest.json``,
  the watcher heartbeat, and directory sizes.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Iterable

from core import events

try:
    from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, HistogramMetricFamily
    PROM_OK = True
except ImportError:      # the metrics server answers 501 in this case; nothing here is reached
    PROM_OK = False

BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_TOOL_TYPES = ("tool.end", "tool.error", "tool.shed")
_BATCH = 1000


def _outcome(ev: dict[str, Any]) -> str:
    if ev["type"] == "tool.end":
        return "ok"
    if ev["type"] == "tool.shed":
        return "shed"
    return "busy" if ev.get("error") == "StoreBusy" else "error"


class StoreCollector:
    """``collect()`` is called by ``prometheus_client`` on every scrape."""

    def __init__(self, store_dir: str, repo: str, repo_root: str) -> None:
        self.store = store_dir
        self.repo = repo
        self.repo_root = repo_root
        self._seq = 0
        self._calls: dict[tuple[str, str], int] = {}
        # tool -> [count per bucket (non-cumulative), +Inf count, sum_seconds]
        self._hist: dict[str, list[float]] = {}
        self._busy = 0
        self._lock = threading.Lock()

    # -- events ----------------------------------------------------------------------------------
    def _ingest(self) -> None:
        while True:
            batch = events.read_since(self.store, self._seq, limit=_BATCH)
            if not batch:
                return
            for ev in batch:
                self._seq = max(self._seq, int(ev.get("seq") or 0))
                if ev.get("type") not in _TOOL_TYPES:
                    continue
                tool = str(ev.get("tool") or "unknown")
                out = _outcome(ev)
                self._calls[(tool, out)] = self._calls.get((tool, out), 0) + 1
                if out == "busy":
                    self._busy += 1
                dur = ev.get("dur_ms")
                if isinstance(dur, (int, float)) and ev["type"] != "tool.shed":
                    h = self._hist.setdefault(tool, [0.0] * (len(BUCKETS) + 2))
                    sec = dur / 1000.0
                    for i, bound in enumerate(BUCKETS):
                        if sec <= bound:
                            h[i] += 1
                            break
                    else:
                        h[len(BUCKETS)] += 1
                    h[len(BUCKETS) + 1] += sec
            if len(batch) < _BATCH:
                return

    # -- store files -----------------------------------------------------------------------------
    def _gauges(self) -> Iterable[Any]:
        from data.graph import graph_seq  # pylint: disable=import-outside-toplevel
        from core.store_stats import store_sizes  # pylint: disable=import-outside-toplevel
        r = self.repo
        g = GaugeMetricFamily("cognirepo_graph_seq", "Knowledge-graph change counter", labels=["repo"])
        g.add_metric([r], graph_seq.read(self.store))
        yield g
        stats = graph_seq.read_stats(self.store)
        if stats:
            n = GaugeMetricFamily("cognirepo_graph_nodes", "Knowledge-graph nodes at the last save", labels=["repo"])
            n.add_metric([r], stats["nodes"])
            e = GaugeMetricFamily("cognirepo_graph_edges", "Knowledge-graph edges at the last save", labels=["repo"])
            e.add_metric([r], stats["edges"])
            yield n
            yield e
        man = _read_json(os.path.join(self.store, "index", "manifest.json")) or {}
        ts = _parse_iso(man.get("indexed_at"))
        if ts is not None:
            age = GaugeMetricFamily("cognirepo_index_age_seconds", "Seconds since the last full index", labels=["repo"])
            age.add_metric([r], max(0.0, time.time() - ts))
            yield age
        for key, name, doc in (("source_file_count", "cognirepo_index_files", "Files in the AST index"),
                               ("symbol_count", "cognirepo_index_symbols", "Symbols in the AST index")):
            if isinstance(man.get(key), int):
                m = GaugeMetricFamily(name, doc, labels=["repo"])
                m.add_metric([r], man[key])
                yield m
        hb = _watcher(self.repo_root, self.store)
        up = GaugeMetricFamily("cognirepo_watcher_up", "1 if a live watcher daemon is registered for the repo", labels=["repo"])
        up.add_metric([r], 1 if hb["state"] in ("running", "stale") else 0)
        yield up
        if hb["heartbeat_age_s"] is not None:
            age = GaugeMetricFamily("cognirepo_watcher_heartbeat_age_seconds", "Seconds since the watcher heartbeat", labels=["repo"])
            age.add_metric([r], hb["heartbeat_age_s"])
            yield age
        sizes = GaugeMetricFamily("cognirepo_store_bytes", "Bytes used by a part of the store", labels=["repo", "part"])
        for part, size in sorted(store_sizes(self.store).items()):
            sizes.add_metric([r, part], size)
        yield sizes
        seq = GaugeMetricFamily("cognirepo_event_seq", "Highest event sequence number seen", labels=["repo"])
        seq.add_metric([r], events.last_seq(self.store))
        yield seq

    def collect(self) -> Iterable[Any]:
        if not PROM_OK:
            return
        with self._lock:
            try:
                self._ingest()
            except Exception:  # pylint: disable=broad-except
                pass   # a torn read must not fail the scrape; the next one picks up from self._seq
            calls = dict(self._calls)
            hist = {k: list(v) for k, v in self._hist.items()}
            busy = self._busy
        c = CounterMetricFamily("cognirepo_tool_calls", "MCP tool calls by outcome", labels=["repo", "tool", "outcome"])
        for (tool, out), n in sorted(calls.items()):
            c.add_metric([self.repo, tool, out], n)
        yield c
        h = HistogramMetricFamily("cognirepo_tool_call_duration_seconds", "MCP tool call duration", labels=["repo", "tool"])
        for tool, row in sorted(hist.items()):
            cum, buckets = 0.0, []
            for i, bound in enumerate(BUCKETS):
                cum += row[i]
                buckets.append((repr(bound), cum))
            cum += row[len(BUCKETS)]
            buckets.append(("+Inf", cum))
            h.add_metric([self.repo, tool], buckets, row[len(BUCKETS) + 1])
        yield h
        b = CounterMetricFamily("cognirepo_store_busy", "Tool calls that gave up waiting for a store lock (retryable)", labels=["repo"])
        b.add_metric([self.repo], busy)
        yield b
        yield from self._gauges()


def _read_json(path: str) -> dict | None:
    import json  # pylint: disable=import-outside-toplevel
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _parse_iso(value: Any) -> float | None:
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


def _watcher(repo_root: str, store: str) -> dict[str, Any]:
    """Read-only watcher view (never deletes stale pid files, unlike the daemon helpers)."""
    from interface.ui import repos  # pylint: disable=import-outside-toplevel
    return repos.watcher_state(repo_root, store)
