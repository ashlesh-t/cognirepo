#!/usr/bin/env python3
# Copyright (c) 2026 Ashlesh T. — AGPL-3.0 (see LICENSE)
"""Measure what N concurrent `cognirepo serve` sessions on ONE repo really cost (#116 spike).

Starts N real MCP stdio servers against ``--repo``, drives each with a real MCP client (initialize, then
a few tool calls so the graph, indexer and embedder are actually loaded), then reports per-process
RSS and PSS (proportional set size: shared pages are split between the processes that share them,
so the PSS *sum* is the honest total) at three moments: idle after connect, after the tool calls,
and after the idle-eviction TTL. Linux only (/proc).

    python scripts/measure_serve_footprint.py --repo /path/to/indexed/repo -n 3 [--evict-wait 0]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from contextlib import AsyncExitStack

QUERIES = ("how is the graph saved", "where are memories stored")


def _kb(pid: int, field: str, file: str) -> int:
    try:
        with open(f"/proc/{pid}/{file}", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith(field):
                    return int(line.split()[1])
    except OSError:
        pass
    return 0


def sample(pids: list[int]) -> dict:
    rows = [{"pid": p, "rss_mb": _kb(p, "VmRSS:", "status") / 1024,
             "pss_mb": _kb(p, "Pss:", "smaps_rollup") / 1024} for p in pids]
    return {"processes": rows, "rss_sum_mb": round(sum(r["rss_mb"] for r in rows), 1),
            "pss_sum_mb": round(sum(r["pss_mb"] for r in rows), 1)}


def _tree_pids(root: int) -> list[int]:
    """The server and any children (the launcher may exec through a shim)."""
    out, todo = [], [root]
    while todo:
        p = todo.pop()
        out.append(p)
        try:
            with open(f"/proc/{p}/task/{p}/children", encoding="utf-8") as fh:
                todo += [int(x) for x in fh.read().split()]
        except OSError:
            pass
    return out


async def run(repo: str, n: int, evict_wait: float) -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    exe = shutil.which("cognirepo")
    params = StdioServerParameters(
        command=exe or sys.executable,
        args=["serve", "--project-dir", repo] if exe else ["-m", "interface.cli.main", "serve", "--project-dir", repo],
        cwd=repo,
        env={**os.environ, "COGNIREPO_NO_WATCHER": "1"},   # measure the sessions, not the watcher
    )
    report: dict = {"repo": repo, "sessions": n}
    async with AsyncExitStack() as stack:
        sessions = []
        for _ in range(n):
            read, write = await stack.enter_async_context(stdio_client(params))
            sess = await stack.enter_async_context(ClientSession(read, write))
            await sess.initialize()
            sessions.append(sess)
        await asyncio.sleep(2)
        children = _children_of_self()
        report["after_connect"] = sample(children)
        for sess in sessions:
            await sess.call_tool("get_session_brief", {})
            for q in QUERIES:
                await sess.call_tool("context_pack", {"query": q})
        report["after_tool_calls"] = sample(children)
        if evict_wait:
            await asyncio.sleep(evict_wait)
            report["after_idle_eviction"] = sample(children)
    return report


def _children_of_self() -> list[int]:
    return [p for p in _tree_pids(os.getpid()) if p != os.getpid()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, help="an already-indexed repo")
    ap.add_argument("-n", type=int, default=3, help="concurrent serve sessions (default 3)")
    ap.add_argument("--evict-wait", type=float, default=0,
                    help="seconds to wait, then sample again (set > idle_ttl_seconds, default 600, to see eviction)")
    args = ap.parse_args()
    if not sys.platform.startswith("linux"):
        print("Linux only (needs /proc)", file=sys.stderr)
        return 2
    print(json.dumps(asyncio.run(run(os.path.abspath(args.repo), args.n, args.evict_wait)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
