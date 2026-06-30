#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""
AST-guided import rewriter for CogniRepo restructure.

Given a JSON mapping of {old_module_prefix: new_module_prefix}, rewrite
every matching import statement in every .py file under the repo root.

Uses ast.parse to locate import line numbers exactly (no false positives on
string literals or comments), then replaces only those lines.

Usage:
    python scripts/rewrite_imports.py --mapping restructure/step-3.1-mapping.json
    python scripts/rewrite_imports.py --mapping restructure/step-3.1-mapping.json --dry-run
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

SKIP_DIRS = {
    "venv", ".venv", "venv_test", "build", "dist",
    ".eggs", ".git", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "restructure",
}


def _should_skip(path: Path) -> bool:
    for part in path.parts:
        if part in SKIP_DIRS or part.endswith(".egg-info"):
            return True
    return False


def _load_mapping(mapping_path: str) -> dict[str, str]:
    with open(mapping_path, encoding="utf-8") as f:
        return json.load(f)


def _find_import_lines(source: str, filepath: str) -> set[int]:
    """Return set of 1-indexed line numbers that are import statements."""
    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        return set()
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # Collect all lines this node spans (handles multiline imports)
            start = node.lineno
            end = getattr(node, "end_lineno", node.lineno)
            for ln in range(start, end + 1):
                lines.add(ln)
    return lines


def _apply_mapping(line: str, mapping: dict[str, str]) -> str:
    """Apply the first matching mapping rule to a line. Returns modified line."""
    for old, new in mapping.items():
        if old in line:
            line = line.replace(old, new, 1)
            break  # apply only one mapping per line
    return line


def rewrite_file(py_file: Path, mapping: dict[str, str], dry_run: bool) -> int:
    """Rewrite imports in one file. Returns count of lines changed."""
    try:
        source = py_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0

    import_line_nums = _find_import_lines(source, str(py_file))
    if not import_line_nums:
        return 0

    lines = source.splitlines(keepends=True)
    changed = 0
    new_lines = []

    for i, line in enumerate(lines, start=1):
        if i in import_line_nums:
            new_line = _apply_mapping(line, mapping)
            if new_line != line:
                if dry_run:
                    rel = py_file.relative_to(REPO_ROOT)
                    print(f"  [{rel}:{i}] - {line.rstrip()}")
                    print(f"  [{rel}:{i}] + {new_line.rstrip()}")
                changed += 1
                new_lines.append(new_line)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    if changed and not dry_run:
        py_file.write_text("".join(new_lines), encoding="utf-8")

    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Rewrite CogniRepo imports")
    parser.add_argument("--mapping", required=True, help="Path to JSON mapping file")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    parser.add_argument("--path", default=None, help="Limit to a specific file or directory")
    args = parser.parse_args()

    mapping = _load_mapping(args.mapping)
    print(f"Loaded {len(mapping)} mapping rules from {args.mapping}", file=sys.stderr)
    if args.dry_run:
        print("[DRY RUN — no files will be written]", file=sys.stderr)

    search_root = Path(args.path) if args.path else REPO_ROOT

    total_files = 0
    total_changes = 0

    for py_file in sorted(search_root.rglob("*.py")):
        rel = py_file.relative_to(REPO_ROOT)
        if _should_skip(rel):
            continue
        n = rewrite_file(py_file, mapping, args.dry_run)
        if n:
            total_files += 1
            total_changes += n
            if not args.dry_run:
                print(f"  Rewrote {n} line(s) in {rel}", file=sys.stderr)

    print(
        f"\nDone: {total_changes} line(s) changed across {total_files} file(s)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
