#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
CI guard: fail if any MCP-critical module contains a print() call to stdout.

MCP servers communicate over stdio (JSON-RPC). Any stray print() in the
memory/server layer that writes to stdout corrupts the JSON-RPC framing.

Prints with ``file=sys.stderr`` are allowed — they go to the diagnostic channel.
Lines inside docstrings or comment blocks are skipped.

Usage:
    python scripts/check_no_stdout_pollution.py

Exit code 0 = clean, 1 = violations found.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Only scan these top-level directories — they are imported by the MCP server
# during normal request handling (not just as CLI scripts).
MCP_CRITICAL_DIRS = {"memory", "server", "retrieval", "vector_db"}

# Match a bare print( call at the start of a non-comment line
_PRINT_RE = re.compile(r"^\s*print\s*\(")
# Exempt: print(..., file=sys.stderr) — writes to the safe diagnostic channel
_STDERR_RE = re.compile(r"file\s*=\s*sys\.stderr")

ROOT = Path(__file__).parent.parent  # repo root


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return (lineno, line) for stdout-going print() calls, skipping comments/docstrings."""
    hits: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return hits

    in_docstring = False
    docstring_char = ""

    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()

        # Toggle docstring state
        for delim in ('"""', "'''"):
            count = stripped.count(delim)
            if not in_docstring and count >= 1:
                in_docstring = True
                docstring_char = delim
                # If opening and closing on same line: not in docstring after this line
                if count >= 2:
                    in_docstring = False
                break
            if in_docstring and docstring_char == delim and count >= 1:
                in_docstring = False
                break

        if in_docstring:
            continue

        # Skip comment lines
        if stripped.startswith("#"):
            continue

        if _PRINT_RE.match(line) and not _STDERR_RE.search(line):
            hits.append((i, line.rstrip()))

    return hits


def main() -> int:
    violations: list[tuple[Path, int, str]] = []
    files_checked = 0

    for py_file in sorted(ROOT.rglob("*.py")):
        parts = py_file.parts
        if any(p in parts for p in ("venv", ".venv", "__pycache__", ".cognirepo")):
            continue
        rel = py_file.relative_to(ROOT)
        top = rel.parts[0] if rel.parts else ""
        if top not in MCP_CRITICAL_DIRS:
            continue
        if py_file.name.startswith("test_") or py_file.name == "conftest.py":
            continue

        files_checked += 1
        for lineno, line in _scan_file(py_file):
            violations.append((rel, lineno, line))

    if violations:
        print(
            "STDOUT POLLUTION CHECK FAILED — bare print() to stdout in MCP-critical modules:\n",
            file=sys.stderr,
        )
        for rel, lineno, line in violations:
            print(f"  {rel}:{lineno}: {line}", file=sys.stderr)
        print(
            f"\n{len(violations)} violation(s) across {files_checked} files. "
            "Replace with logger.debug(...) or add file=sys.stderr.",
            file=sys.stderr,
        )
        return 1

    print(f"stdout-pollution check passed — 0 violations in {files_checked} MCP-critical files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
