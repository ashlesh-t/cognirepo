# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""`cognirepo doctor --resources` — where the memory and disk go (COGNIREPO-121).

One report, read-only, three questions:

* **Processes** — every running cognirepo process (watchers, MCP ``serve`` sessions, one-shot
  commands): resident memory, age, which repo, and whether it looks stale (see ``proc_scan``).
* **Stores** — size of each ``.cognirepo`` subdirectory, largest first, with the biggest files.
* **Set-aside files** — quarantines (``*.corrupt-*``), replaced files, ``.stale`` indexes and left-over
  scratch files: the bytes nobody is using but nobody deleted.

Processes come from ``/proc`` (Linux); elsewhere that section says so. Nothing here changes anything.
"""
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass

#: names of files/dirs the loaders set aside or leave behind (see docs/RESOURCES.md for each)
_SET_ASIDE = re.compile(
    r"(\.corrupt-\d+$|\.replaced-\d+$|\.stale$|\.tmp$|\.bak$|^\.opening\.\d+$|^\.open\.\d+$)"
)
_TOP_FILES = 5


@dataclass
class StoreDir:
    name: str
    bytes: int
    files: int
    largest: "list[tuple[str, int]]"      # (relative path, bytes), biggest first


@dataclass
class SetAside:
    path: str            # relative to the store root
    bytes: int
    kind: str            # quarantine | replaced | stale-index | scratch | marker


def _kind(name: str) -> str:
    if ".corrupt-" in name:
        return "quarantine"
    if ".replaced-" in name:
        return "replaced"
    if name.endswith(".stale"):
        return "stale-index"
    if name.startswith((".opening.", ".open.")):
        return "marker"
    return "scratch"


def _tree_size(path: str) -> "tuple[int, int, list[tuple[str, int]]]":
    """(bytes, file count, largest files) of a file or directory tree; symlinks are not followed."""
    total, count, big = 0, 0, []
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            st = os.lstat(cur)
        except OSError:
            continue
        if os.path.isdir(cur) and not os.path.islink(cur):
            try:
                with os.scandir(cur) as it:
                    stack.extend(e.path for e in it)
            except OSError:
                pass
        else:
            total += st.st_size
            count += 1
            big.append((cur, st.st_size))
    big.sort(key=lambda x: x[1], reverse=True)
    return total, count, big[:_TOP_FILES]


def store_sizes(root: str) -> "list[StoreDir]":
    """Size of each immediate child of ``root`` (files at the top level are grouped), biggest first."""
    out: "list[StoreDir]" = []
    loose = StoreDir("(top-level files)", 0, 0, [])
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for name in names:
        p = os.path.join(root, name)
        size, n, big = _tree_size(p)
        if os.path.isdir(p) and not os.path.islink(p):
            out.append(StoreDir(name, size, n, [(os.path.relpath(f, root), s) for f, s in big]))
        else:
            loose.bytes += size
            loose.files += n
            loose.largest.extend((os.path.relpath(f, root), s) for f, s in big)
    if loose.files:
        loose.largest.sort(key=lambda x: x[1], reverse=True)
        loose.largest = loose.largest[:_TOP_FILES]
        out.append(loose)
    return sorted(out, key=lambda d: d.bytes, reverse=True)


def set_aside_files(root: str, max_depth: int = 3) -> "list[SetAside]":
    """Quarantines, replaced files, stale indexes and scratch files under ``root`` (depth-limited)."""
    found: "list[SetAside]" = []

    def walk(d: str, depth: int) -> None:
        try:
            entries = list(os.scandir(d))
        except OSError:
            return
        for e in entries:
            if _SET_ASIDE.search(e.name):
                size, _n, _b = _tree_size(e.path)
                found.append(SetAside(os.path.relpath(e.path, root), size, _kind(e.name)))
            elif e.is_dir(follow_symlinks=False) and depth < max_depth:
                walk(e.path, depth + 1)

    walk(root, 1)
    return sorted(found, key=lambda s: s.bytes, reverse=True)


def process_report() -> dict:
    """Running cognirepo processes with memory, age, repo and a stale flag."""
    from interface.cli import proc_scan  # pylint: disable=import-outside-toplevel
    if not os.path.isdir("/proc"):
        return {"supported": False, "processes": [], "total_rss_mb": 0.0, "stale_rss_mb": 0.0}
    procs = proc_scan.scan()
    stale = {p.pid: why for p, why in proc_scan.find_stale(procs)}
    rows = []
    for p in sorted(procs, key=lambda x: x.rss_mb, reverse=True):
        rows.append({
            "pid": p.pid, "command": p.command, "rss_mb": round(p.rss_mb, 1),
            "age_hours": round(p.age_secs / 3600, 1), "repo": p.cwd,
            "stale": stale.get(p.pid),
        })
    return {
        "supported": True, "processes": rows,
        "total_rss_mb": round(sum(r["rss_mb"] for r in rows), 1),
        "stale_rss_mb": round(sum(r["rss_mb"] for r in rows if r["stale"]), 1),
    }


def collect(root: str) -> dict:
    stores = store_sizes(root)
    aside = set_aside_files(root)
    return {
        "root": root,
        "processes": process_report(),
        "stores": [asdict(s) for s in stores],
        "total_bytes": sum(s.bytes for s in stores),
        "set_aside": [asdict(a) for a in aside],
        "set_aside_bytes": sum(a.bytes for a in aside),
    }


def _mb(n: float) -> str:
    return f"{n / (1024 * 1024):,.1f} MB" if n >= 1024 * 1024 else f"{n / 1024:,.1f} KB"


def render(report: dict, max_rows: int = 12) -> str:
    out = [f"CogniRepo resource report — {report['root']}", ""]
    pr = report["processes"]
    out.append("Processes")
    if not pr["supported"]:
        out.append("  (process listing needs /proc — Linux only)")
    elif not pr["processes"]:
        out.append("  no cognirepo processes running")
    else:
        out.append(f"  {'PID':>7}  {'COMMAND':<14} {'RSS':>10}  {'AGE':>7}  REPO")
        for r in pr["processes"][:max_rows]:
            flag = "   <- STALE: " + r["stale"] if r["stale"] else ""
            out.append(f"  {r['pid']:>7}  {r['command']:<14} {r['rss_mb']:>7.1f} MB  "
                       f"{r['age_hours']:>5.1f}h  {r['repo']}{flag}")
        if len(pr["processes"]) > max_rows:
            out.append(f"  … and {len(pr['processes']) - max_rows} more")
        line = f"  total {pr['total_rss_mb']:,.1f} MB resident"
        if pr["stale_rss_mb"]:
            line += f", of which {pr['stale_rss_mb']:,.1f} MB is in stale processes (run `cognirepo doctor`)"
        out.append(line)
    out += ["", f"Stores under .cognirepo/  (total {_mb(report['total_bytes'])})"]
    for s in report["stores"]:
        out.append(f"  {_mb(s['bytes']):>12}  {s['name']:<18} {s['files']} file(s)")
        for rel, size in s["largest"][:2]:
            if size >= 1024 * 1024:
                out.append(f"  {'':>12}    └ {rel}  {_mb(size)}")
    aside = report["set_aside"]
    out += ["", "Set-aside and left-over files"]
    if not aside:
        out.append("  none")
    else:
        for a in aside[:max_rows]:
            out.append(f"  {_mb(a['bytes']):>12}  {a['kind']:<11} {a['path']}")
        if len(aside) > max_rows:
            out.append(f"  … and {len(aside) - max_rows} more")
        out.append(f"  total {_mb(report['set_aside_bytes'])}. Graph quarantines may hold a recoverable graph: "
                   "see `cognirepo graph restore` before deleting anything.")
    return "\n".join(out)
