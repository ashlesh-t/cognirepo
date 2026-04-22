# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Language registry for the CogniRepo multi-language AST indexer.

Maps file extensions to tree-sitter grammar packages.  Grammars are
optional — install them with:

    pip install 'cognirepo[languages]'

Python files have an additional stdlib-ast fallback so CogniRepo always
indexes Python even without the tree-sitter-python grammar package.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# extension → tree-sitter grammar package name
_GRAMMAR_MAP: dict[str, str] = {
    ".py":   "tree_sitter_python",
    ".js":   "tree_sitter_javascript",
    ".jsx":  "tree_sitter_javascript",
    ".ts":   "tree_sitter_typescript",
    ".tsx":  "tree_sitter_typescript",
    ".java": "tree_sitter_java",
    ".cpp":  "tree_sitter_cpp",
    ".cc":   "tree_sitter_cpp",
    ".h":    "tree_sitter_cpp",
    ".hpp":  "tree_sitter_cpp",
    ".go":   "tree_sitter_go",
    ".rs":   "tree_sitter_rust",
    ".sh":   "tree_sitter_bash",
    ".bash": "tree_sitter_bash",
    ".yml":  "tree_sitter_yaml",
    ".yaml": "tree_sitter_yaml",
}

# Some grammar packages expose multiple language() functions instead of
# the standard single language() function.  Map ext → (package, func_name).
_GRAMMAR_FUNC_OVERRIDE: dict[str, tuple[str, str]] = {
    ".ts":  ("tree_sitter_typescript", "language_typescript"),
    ".tsx": ("tree_sitter_typescript", "language_tsx"),
}

# Human-readable language labels (used in index-repo summary output)
_LANG_LABELS: dict[str, str] = {
    ".py":   "Python",
    ".js":   "JavaScript",
    ".ts":   "TypeScript",
    ".jsx":  "JavaScript",
    ".tsx":  "TypeScript",
    ".java": "Java",
    ".cpp":  "C++",
    ".cc":   "C++",
    ".h":    "C++",
    ".hpp":  "C++",
    ".go":   "Go",
    ".rs":   "Rust",
    ".sh":   "Shell",
    ".bash": "Shell",
    ".pyi":  "Python",
    ".yml":  "YAML",
    ".yaml": "YAML",
}

# Language identifiers used internally (e.g. for docstring extraction heuristics)
_LANG_NAMES: dict[str, str] = {
    ".py":   "python",
    ".js":   "javascript",
    ".jsx":  "javascript",
    ".ts":   "typescript",
    ".tsx":  "tsx",
    ".java": "java",
    ".cpp":  "cpp",
    ".cc":   "cpp",
    ".h":    "cpp",
    ".hpp":  "cpp",
    ".go":   "go",
    ".rs":   "rust",
    ".sh":   "bash",
    ".bash": "bash",
    ".pyi":  "python",
    ".yml":  "yaml",
    ".yaml": "yaml",
}

# Python can be indexed via stdlib ast even without tree-sitter-python
_PYTHON_FALLBACK_EXTS: frozenset[str] = frozenset({".py", ".pyi"})

# Module level cache: ext → Language object or None
_lang_cache: dict[str, object] = {}
_TS_AVAILABLE: bool | None = None  # pylint: disable=invalid-name  # lazy: None = unchecked


def _tree_sitter_available() -> bool:
    global _TS_AVAILABLE  # pylint: disable=global-statement
    if _TS_AVAILABLE is None:
        try:
            importlib.import_module("tree_sitter")
            _TS_AVAILABLE = True
        except ImportError:
            _TS_AVAILABLE = False
    return _TS_AVAILABLE



def _get_language(ext: str):
    """
    Return a tree_sitter.Language for *ext*, or None if:
      - the extension is unknown, or
      - the grammar package is not installed, or
      - tree-sitter itself is not installed.

    Results are cached so each grammar is loaded at most once per process.
    """
    if ext in _lang_cache:
        return _lang_cache[ext]

    if not _tree_sitter_available():
        _lang_cache[ext] = None
        return None

    pkg = _GRAMMAR_MAP.get(ext)
    if not pkg:
        _lang_cache[ext] = None
        return None

    try:
        from tree_sitter import Language  # pylint: disable=import-outside-toplevel
        override = _GRAMMAR_FUNC_OVERRIDE.get(ext)
        if override:
            pkg_name, func_name = override
            mod = importlib.import_module(pkg_name)
            lang = Language(getattr(mod, func_name)())
        else:
            mod = importlib.import_module(pkg)
            lang = Language(mod.language())
        _lang_cache[ext] = lang
        return lang
    except ImportError:
        log.debug(
            "Grammar package '%s' not installed — %s files will be skipped "
            "(run: pip install 'cognirepo[languages]')",
            pkg, ext,
        )
    except Exception as exc:  # pylint: disable=broad-except
        log.debug("Failed to load grammar for '%s': %s", ext, exc)

    _lang_cache[ext] = None
    return None


# ── public API ────────────────────────────────────────────────────────────────

def supported_extensions() -> list[str]:
    """
    Return the list of file extensions for which a grammar package is
    currently installed.  Always includes .py (stdlib fallback).
    """
    result = list(_PYTHON_FALLBACK_EXTS)
    for ext in _GRAMMAR_MAP:
        if ext in _PYTHON_FALLBACK_EXTS:
            continue
        if _get_language(ext) is not None:
            result.append(ext)
    return result


def is_supported(path: "Path | str") -> bool:
    """
    Return True if *path* can be indexed — either a grammar is installed
    or a stdlib fallback exists (Python).
    """
    suffix = Path(path).suffix
    return _get_language(suffix) is not None or suffix in _PYTHON_FALLBACK_EXTS


def lang_label(ext: str) -> str:
    """Return the human-readable label for an extension (e.g. '.java' → 'Java')."""
    return _LANG_LABELS.get(ext, ext.lstrip(".").upper())


def lang_name(ext: str) -> str:
    """Return the internal language name for an extension (e.g. '.py' → 'python')."""
    return _LANG_NAMES.get(ext, ext.lstrip("."))


def clear_cache() -> None:
    """Reset the language cache (useful in tests that monkeypatch importlib)."""
    _lang_cache.clear()
    global _TS_AVAILABLE  # pylint: disable=global-statement
    _TS_AVAILABLE = None
