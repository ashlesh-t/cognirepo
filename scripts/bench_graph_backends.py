#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Compare the networkx (graph.pkl) and SQLite graph backends on a synthetic code graph (#115, ADR 002).

    python scripts/bench_graph_backends.py --nodes 100000 --degree 6

Each measurement runs in its OWN process, so peak RSS is honest (a shared interpreter would carry
the other backend's garbage). Per backend it reports: build time and on-disk size, then — in a fresh
process, which is what every `cognirepo serve` / CLI call is — time to open, RSS after open and after a
query workload, and p50/p95 latency of the calls retrieval makes (successors, predecessors,
subgraph_around radius 2, hop_distance). The graph is synthetic (files -> symbols -> calls with locality
plus a few hubs); real repos differ, so treat the shape of the result, not the absolute numbers, as the finding.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rss_mb() -> float:
    with open("/proc/self/status", encoding="ascii") as fh:
        for line in fh:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    return 0.0


def _peak_mb() -> float:
    import resource  # pylint: disable=import-outside-toplevel
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def _symbols(n: int) -> list[str]:
    return [f"pkg{i // 400}/mod{i // 20}.py::fn{i}" for i in range(n)]


def child_build(n: int, degree: int) -> dict:
    from data.graph.knowledge_graph import EdgeType, KnowledgeGraph, NodeType
    rnd = random.Random(7)
    syms = _symbols(n)
    t0 = time.perf_counter()
    g = KnowledgeGraph()
    g.begin_journal(flush_ops=20_000)
    seen_files = set()
    for i, s in enumerate(syms):
        f = s.split("::")[0]
        if f not in seen_files:
            seen_files.add(f)
            g.add_node(f, NodeType.FILE)
        g.add_node(s, NodeType.FUNCTION, file=f, line=i % 900, doc="x" * 40)
        g.add_edge(s, f, EdgeType.DEFINED_IN)
    hubs = syms[:20]
    for i, s in enumerate(syms):
        for _ in range(degree):
            j = (i + int(rnd.expovariate(1 / 60))) % n if rnd.random() < 0.8 else rnd.randrange(n)
            tgt = hubs[rnd.randrange(len(hubs))] if rnd.random() < 0.03 else syms[j]
            g.add_edge(s, tgt, EdgeType.CALLED_BY)
            g.add_edge(tgt, s, EdgeType.CALLS)
    g.mark_complete()
    g.end_journal()
    g.save()
    secs = time.perf_counter() - t0
    graph_dir = os.path.join(os.environ["BENCH_STORE"], "graph")
    size = sum(os.path.getsize(os.path.join(graph_dir, f)) for f in os.listdir(graph_dir)
               if f.startswith("graph.") and not f.endswith((".lock", ".pid", ".writer", ".seq", ".stats")))
    return {"build_s": round(secs, 1), "disk_mb": round(size / 1e6, 1), "peak_rss_mb": round(_peak_mb()),
            "nodes": g.node_count(), "edges": g.edge_count()}


def _timed(fn, args_list) -> dict:
    lat = []
    for a in args_list:
        t = time.perf_counter()
        fn(*a)
        lat.append((time.perf_counter() - t) * 1000)
    lat.sort()
    return {"p50_ms": round(statistics.median(lat), 3), "p95_ms": round(lat[int(len(lat) * 0.95) - 1], 3)}


def child_query(n: int) -> dict:
    from data.graph.knowledge_graph import KnowledgeGraph
    rnd = random.Random(11)
    syms = _symbols(n)
    t0 = time.perf_counter()
    g = KnowledgeGraph()
    g.node_count()
    opened = time.perf_counter() - t0
    rss_open = _rss_mb()
    picks = [syms[rnd.randrange(n)] for _ in range(2000)]
    pairs = [(picks[i], picks[i + 1]) for i in range(0, 400, 2)]
    out = {
        "open_s": round(opened, 2), "rss_after_open_mb": round(rss_open),
        "successors": _timed(lambda s: g.successors(s), [(p,) for p in picks]),
        "predecessors": _timed(lambda s: g.predecessors(s), [(p,) for p in picks]),
        "subgraph_r2": _timed(lambda s: g.subgraph_around(s, radius=2), [(p,) for p in picks[:300]]),
        "hop_distance": _timed(g.hop_distance, pairs),
        "node_attrs": _timed(lambda s: g.node_attrs(s), [(p,) for p in picks]),
    }
    out["rss_after_queries_mb"] = round(_rss_mb())
    out["peak_rss_mb"] = round(_peak_mb())
    return out


def run_child(backend: str, store: str, what: str, n: int, degree: int) -> dict:
    env = {**os.environ, "COGNIREPO_GRAPH_BACKEND": backend, "BENCH_STORE": store,
           "PYTHONPATH": ROOT, "COGNIREPO_EVENTS": "0"}
    code = f"import sys; sys.path.insert(0, {ROOT!r}); " \
           f"from core.config.paths import set_cognirepo_dir; set_cognirepo_dir({store!r}); " \
           f"import scripts.bench_graph_backends as b, json; print('@@' + json.dumps(b.child_{what}(" \
           + (f"{n}, {degree}" if what == "build" else f"{n}") + ")))"
    proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=False)
    for line in proc.stdout.splitlines():
        if line.startswith("@@"):
            return json.loads(line[2:])
    raise SystemExit(f"{backend} {what} failed:\n{proc.stdout[-800:]}\n{proc.stderr[-1500:]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--nodes", type=int, default=50_000)
    ap.add_argument("--degree", type=int, default=6, help="calls per symbol")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    results: dict = {"nodes_requested": args.nodes, "degree": args.degree}
    with tempfile.TemporaryDirectory(prefix="cr-graphbench-") as tmp:
        for backend in ("networkx", "sqlite"):
            store = os.path.join(tmp, backend, ".cognirepo")
            os.makedirs(os.path.join(store, "graph"))
            results[backend] = {"build": run_child(backend, store, "build", args.nodes, args.degree),
                                "query": run_child(backend, store, "query", args.nodes, args.degree)}
    if args.json:
        print(json.dumps(results, indent=2))
        return
    nx_, sq = results["networkx"], results["sqlite"]
    print(f"synthetic graph: {nx_['build']['nodes']:,} nodes, {nx_['build']['edges']:,} edges")
    rows = [
        ("build (s)", nx_["build"]["build_s"], sq["build"]["build_s"]),
        ("disk (MB)", nx_["build"]["disk_mb"], sq["build"]["disk_mb"]),
        ("build peak RSS (MB)", nx_["build"]["peak_rss_mb"], sq["build"]["peak_rss_mb"]),
        ("open (s)", nx_["query"]["open_s"], sq["query"]["open_s"]),
        ("RSS after open (MB)", nx_["query"]["rss_after_open_mb"], sq["query"]["rss_after_open_mb"]),
        ("RSS after queries (MB)", nx_["query"]["rss_after_queries_mb"], sq["query"]["rss_after_queries_mb"]),
    ]
    for key in ("successors", "predecessors", "node_attrs", "subgraph_r2", "hop_distance"):
        rows.append((f"{key} p50/p95 (ms)", f'{nx_["query"][key]["p50_ms"]} / {nx_["query"][key]["p95_ms"]}',
                     f'{sq["query"][key]["p50_ms"]} / {sq["query"][key]["p95_ms"]}'))
    print(f"{'':28}{'networkx':>20}{'sqlite':>20}")
    for name, a, b in rows:
        print(f"{name:28}{a!s:>20}{b!s:>20}")


if __name__ == "__main__":
    main()
