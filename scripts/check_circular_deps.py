#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""
Check for circular dependencies between layers in the CogniRepo restructure.

Reads the import-graph.json produced by build_import_graph.py, maps each
package to its target layer, and verifies no layer imports from a layer
above it in the dependency stack.

Both top-level AND lazy (inside function/class bodies) upward imports are hard
failures — a lazy import doesn't create a runtime import *cycle*, but it's
still a `data → interface`-shaped dependency an interface-layer caller has to
inject instead (see COGNIREPO-105 / IMPROVEMENTS.md item 1). Only
TYPE_CHECKING-guarded imports are allowlisted, since those have zero runtime
effect.

Layer order (lowest to highest):
  0: core        — config, security, vector_db, _bm25
  1: data        — memory, graph
  2: intelligence — indexer, retrieval, orchestrator
  3: interface   — tools, server, adapters
  4: ops         — cron
  5: cli         — cli top-level consumer

Usage:
    python scripts/check_circular_deps.py restructure/import-graph.json
    python scripts/check_circular_deps.py restructure/import-graph.json --verbose
"""
from __future__ import annotations

import argparse
import json
import sys

LAYER_MAP: dict[str, int] = {
    "core": 0, "config": 0, "security": 0, "vector_db": 0, "_bm25": 0,
    "data": 1, "memory": 1, "graph": 1,
    "intelligence": 2, "indexer": 2, "retrieval": 2, "orchestrator": 2,
    "interface": 3, "tools": 3, "server": 3, "adapters": 3,
    "ops": 4, "cron": 4,
    "cli": 5, "cognirepo": 5,
}

LAYER_NAMES = {0: "core", 1: "data", 2: "intelligence", 3: "interface", 4: "ops", 5: "cli"}


def _pkg_of_file(filepath: str) -> str:
    parts = filepath.replace("\\", "/").split("/")
    if len(parts) >= 2 and parts[0] == "interface" and parts[1] == "cli":
        return "cli"
    return parts[0] if parts else ""


def _pkg_of_module(module: str) -> str:
    return module.split(".")[0] if module else ""


def check(graph_path: str, verbose: bool) -> bool:
    with open(graph_path, encoding="utf-8") as f:
        graph = json.load(f)

    violations: list[str] = []      # toplevel upward deps — hard failures
    lazy_violations: list[str] = []  # lazy upward deps — also hard failures (COGNIREPO-105)
    type_check_upward: list[str] = []  # TYPE_CHECKING upward — no runtime impact

    for filepath, info in graph["files"].items():
        src_pkg = _pkg_of_file(filepath)
        src_layer = LAYER_MAP.get(src_pkg)
        if src_layer is None:
            continue

        for imp in info.get("internal_imports", []):
            dep_module = imp.get("from") or imp.get("module", "")
            dep_pkg = _pkg_of_module(dep_module)
            dep_layer = LAYER_MAP.get(dep_pkg)
            if dep_layer is None or dep_layer <= src_layer:
                continue

            src_name = LAYER_NAMES.get(src_layer, str(src_layer))
            dep_name = LAYER_NAMES.get(dep_layer, str(dep_layer))
            msg = (
                f"{filepath}:{imp.get('lineno','?')} "
                f"[{src_name}] → {dep_module} [{dep_name}]"
            )

            kind = imp.get("kind", "toplevel")
            if kind == "type_check":
                type_check_upward.append(msg)
            elif kind == "lazy":
                lazy_violations.append(msg)
            else:  # toplevel — hard violation
                violations.append(msg)

    if violations:
        print(f"[HARD VIOLATION — toplevel upward import] {len(violations)} found:")
        for msg in violations:
            print(f"  ✗ {msg}")

    if lazy_violations:
        print(f"[HARD VIOLATION — lazy upward import] {len(lazy_violations)} found:")
        for msg in lazy_violations:
            print(f"  ✗ {msg}")

    if verbose and type_check_upward:
        print(f"\n[TYPE_CHECKING — no runtime impact] {len(type_check_upward)}:")
        for msg in type_check_upward:
            print(f"  i {msg}")

    total_violations = len(violations) + len(lazy_violations)
    if total_violations:
        print(
            f"\n✗ {total_violations} hard violation(s) "
            f"({len(violations)} toplevel, {len(lazy_violations)} lazy). "
            f"({len(type_check_upward)} type-check noted, informational.)",
            file=sys.stderr,
        )
        return False

    print(
        f"✓ No hard violations (toplevel or lazy). "
        f"({len(type_check_upward)} TYPE_CHECKING — informational.)"
    )
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Check layer circular deps")
    parser.add_argument("graph", help="Path to import-graph.json")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show lazy/type_check details")
    args = parser.parse_args()

    ok = check(args.graph, args.verbose)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
