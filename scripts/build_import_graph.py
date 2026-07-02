#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""
Build a cross-package import graph for CogniRepo.

Walk every .py file (excluding venv/build/dist/tests), parse with ast,
classify each import as internal (matches a known cognirepo package) or
external, and output restructure/import-graph.json.

Import kinds:
  toplevel    — at module scope, not inside TYPE_CHECKING
  lazy        — inside a function/class body
  type_check  — inside `if TYPE_CHECKING:` block (no runtime dep)
"""
from __future__ import annotations

import ast
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

INTERNAL_PACKAGES = {
    "config", "security", "vector_db", "_bm25",
    "memory", "graph",
    "indexer", "retrieval", "orchestrator",
    "tools", "server", "adapters", "cli",
    "cron",
    "cognirepo",
}

SKIP_DIRS = {
    "venv", ".venv", "venv_test", "build", "dist",
    ".eggs", "*.egg-info", ".git", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "restructure",
}


def _should_skip(path: Path) -> bool:
    for part in path.parts:
        if part in SKIP_DIRS or part.endswith(".egg-info"):
            return True
    return False


def _module_root(module: str) -> str:
    return module.split(".")[0] if module else ""


def _is_type_checking_block(node: ast.AST, tree: ast.Module) -> bool:
    """Return True if the node is directly inside an `if TYPE_CHECKING:` block."""
    for item in ast.walk(tree):
        if not isinstance(item, ast.If):
            continue
        test = item.test
        # Match `if TYPE_CHECKING:` or `if typing.TYPE_CHECKING:`
        is_tc = (
            (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or
            (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")
        )
        if is_tc:
            for child in ast.walk(item):
                if child is node:
                    return True
    return False


def _classify_import(node: ast.AST, tree: ast.Module, module_body: list) -> str:
    """Return 'toplevel', 'lazy', or 'type_check'."""
    if _is_type_checking_block(node, tree):
        return "type_check"
    # If the node is a direct child of the module body, it's toplevel
    if node in module_body:
        return "toplevel"
    return "lazy"


def _extract_imports(source: str, filepath: str) -> tuple[list[dict], list[str]]:
    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        return [], []

    module_body = list(tree.body)
    internal: list[dict] = []
    external: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = _module_root(module)
            names = [alias.name for alias in node.names]
            if root in INTERNAL_PACKAGES:
                kind = _classify_import(node, tree, module_body)
                internal.append({
                    "type": "from",
                    "from": module,
                    "names": names,
                    "lineno": node.lineno,
                    "kind": kind,
                })
            elif root:
                external.add(root)

        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = _module_root(alias.name)
                if root in INTERNAL_PACKAGES:
                    kind = _classify_import(node, tree, module_body)
                    internal.append({
                        "type": "import",
                        "module": alias.name,
                        "lineno": node.lineno,
                        "kind": kind,
                    })
                elif root:
                    external.add(root)

    return internal, sorted(external)


def build_graph() -> dict:
    files: dict[str, dict] = {}
    reverse_deps: dict[str, set] = defaultdict(set)

    for py_file in sorted(REPO_ROOT.rglob("*.py")):
        rel = py_file.relative_to(REPO_ROOT)
        if _should_skip(rel):
            continue

        source = py_file.read_text(encoding="utf-8", errors="replace")
        internal_imports, external = _extract_imports(source, str(py_file))

        files[str(rel)] = {
            "internal_imports": internal_imports,
            "external_imports": external,
        }

        file_pkg = str(rel).split(os.sep)[0]
        for imp in internal_imports:
            if imp.get("kind") == "type_check":
                continue  # TYPE_CHECKING blocks are not runtime deps
            dep_pkg = _module_root(imp.get("from") or imp.get("module", ""))
            if dep_pkg and dep_pkg != file_pkg:
                reverse_deps[dep_pkg].add(file_pkg)

    return {
        "files": files,
        "reverse_deps": {k: sorted(v) for k, v in sorted(reverse_deps.items())},
    }


def main() -> None:
    out_dir = REPO_ROOT / "restructure"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "import-graph.json"

    print("Building import graph...", file=sys.stderr)
    graph = build_graph()

    out_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    print(f"Written: {out_path}", file=sys.stderr)
    print(f"Files scanned: {len(graph['files'])}", file=sys.stderr)
    print(f"Packages with dependents: {len(graph['reverse_deps'])}", file=sys.stderr)


if __name__ == "__main__":
    main()
