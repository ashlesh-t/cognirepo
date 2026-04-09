# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
CI test — verify that every declared grammar in language_registry.py
can be imported and parses a one-line fixture.

Tests are XFAIL (not ERROR) if the grammar package is not installed.
This lets the base install pass CI while the [languages] extra proves
each grammar end-to-end.
"""
from __future__ import annotations

import importlib

import pytest

# Map extension → one-liner source snippet to parse
_FIXTURES: dict[str, tuple[str, str]] = {
    ".py":   ("tree_sitter_python",   "x = 1\n"),
    ".js":   ("tree_sitter_javascript", "var x = 1;\n"),
    ".ts":   ("tree_sitter_typescript", "let x: number = 1;\n"),
    ".java": ("tree_sitter_java",     "class A {}\n"),
    ".go":   ("tree_sitter_go",       "package main\n"),
    ".rs":   ("tree_sitter_rust",     "fn main() {}\n"),
    ".cpp":  ("tree_sitter_cpp",      "int main() { return 0; }\n"),
}


def _grammar_installed(pkg: str) -> bool:
    try:
        importlib.import_module(pkg)
        return True
    except ImportError:
        return False


@pytest.mark.parametrize("ext,args", list(_FIXTURES.items()))
def test_grammar_parses_fixture(ext, args):
    pkg, source = args
    if not _grammar_installed(pkg):
        pytest.xfail(
            reason=f"Grammar package '{pkg}' not installed "
                   f"(install with: pip install 'cognirepo[languages]')"
        )

    tree_sitter = importlib.import_module("tree_sitter")
    Language = tree_sitter.Language
    Parser = tree_sitter.Parser

    mod = importlib.import_module(pkg)
    # TypeScript needs special handling (two language funcs)
    if ext == ".ts":
        lang = Language(mod.language_typescript())
    elif ext == ".tsx":
        lang = Language(mod.language_tsx())
    else:
        lang = Language(mod.language())

    parser = Parser(lang)
    tree = parser.parse(source.encode())
    assert tree is not None
    assert tree.root_node is not None
    # Root node must not be a pure error node
    assert tree.root_node.type != "ERROR", f"Parse error for {ext}: {source!r}"


def test_language_registry_declared_grammars_importable():
    """All grammars in _GRAMMAR_MAP must either import or report a clean skip."""
    from indexer.language_registry import _GRAMMAR_MAP  # pylint: disable=import-outside-toplevel
    missing = []
    for ext, pkg in _GRAMMAR_MAP.items():
        if not _grammar_installed(pkg):
            missing.append(f"{ext}→{pkg}")

    if missing:
        pytest.xfail(
            f"Grammar packages not installed (run: pip install 'cognirepo[languages]'): "
            + ", ".join(missing)
        )
