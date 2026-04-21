# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
AST indexer — walks a repo, extracts symbols from any supported language,
embeds them into a FAISS index, and builds a reverse index (symbol → [(file, line)]).

Parser strategy:
  - tree-sitter  (preferred): consistent API across 40+ languages via grammar packages.
                               Install grammars with:  pip install cognirepo[languages]
  - stdlib ast   (fallback):  Python-only, used automatically when tree-sitter-python
                               is not installed.  Zero extra deps.

FAISS index type: IndexIDMap2(IndexFlatL2(384))
  — unlike semantic.index (IndexFlatL2) this supports remove_ids() so
    individual files can be cleanly re-indexed without a full rebuild.

Persistence:
  .cognirepo/index/ast_index.json     — full index + reverse_index dict
  .cognirepo/index/ast.index          — FAISS index
  .cognirepo/index/ast_metadata.json  — parallel metadata list (faiss_id → record)
"""
from __future__ import annotations

import ast
import functools
import hashlib
import json
import logging
import os
import platform
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import faiss
import numpy as np

from graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType
from graph.graph_utils import make_node_id, node_id_from_symbol_record
from indexer.index_utils import SymbolTable, build_symbol_table_from_index
from indexer.language_registry import (
    _get_language,
    is_supported,
    lang_label,
    lang_name,
)
from memory.embeddings import get_model

log = logging.getLogger(__name__)

from config.paths import get_path

def _ast_index_file() -> str:
    return get_path("index/ast_index.json")

def _ast_faiss_file() -> str:
    return get_path("index/ast.index")

def _ast_meta_file() -> str:
    return get_path("index/ast_metadata.json")

def _manifest_file() -> str:
    return get_path("index/manifest.json")

_SKIP_DIRS: frozenset[str] = frozenset({
    # Version control
    ".git", ".svn", ".hg",
    # Python
    "venv", ".venv", "env", "__pycache__", ".eggs", ".tox",
    ".nox", ".pytest_cache", ".mypy_cache", "htmlcov", "site-packages",
    # Node / JS / TS
    "node_modules", ".next", ".nuxt", ".svelte-kit",
    ".turbo", ".parcel-cache", ".cache", "storybook-static",
    # Java / Kotlin / Gradle
    ".gradle", "gradle", "out", "classes", "generated", "generated-sources", "gen",
    ".idea",
    # Go
    "vendor",
    # General build
    "dist", "build", "target", "bin",
    # CogniRepo internal
    ".cognirepo",
    # Misc generated / temp
    "tmp", "temp", "logs", ".terraform", ".serverless", "__mocks__",
    "coverage",
})

# Maximum file size to index (bytes). Files larger than this are skipped.
_MAX_FILE_BYTES: int = 300_000  # 300 KB

# Threshold above which a large-repo embed warning is printed.
_LARGE_REPO_FILE_THRESHOLD: int = 3_000


def _print_cold_start_banner() -> None:
    """
    Print a cold-start transparency banner when graph/behaviour scores are zero.
    Shown after index-repo and cognirepo init so users understand the warm-up state.
    """
    try:
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        from graph.behaviour_tracker import BehaviourTracker  # pylint: disable=import-outside-toplevel
        kg = KnowledgeGraph()
        bt = BehaviourTracker(kg)
        g_nodes = kg.G.number_of_nodes()
        b_weights = len(bt.data.get("symbol_weights", {}))

        graph_score_str = "warm" if g_nodes > 10 else "0.0 (cold)"
        behaviour_str = "warm" if b_weights > 50 else f"0.0 (needs ~50 queries to calibrate, have {b_weights})"
        is_cold = g_nodes <= 10 or b_weights <= 0

        if is_cold:
            print("\n  Cold-start status:")
            print(f"    graph_score     : {graph_score_str}")
            print(f"    behaviour_score : {behaviour_str}")
            if g_nodes <= 10:
                print("    Currently running: pure vector search")
                print("    Run `cognirepo seed --from-git` to prime graph from git history")
            print()
    except Exception:  # pylint: disable=broad-except
        pass  # banner is informational only


def _effective_skip_dirs() -> frozenset[str]:
    """Return _SKIP_DIRS merged with any extra dirs from .cognirepo/config.json."""
    try:
        with open(get_path("config.json"), encoding="utf-8") as _f:
            _cfg = json.load(_f)
        extra: list[str] = _cfg.get("indexing", {}).get("skip_dirs", [])
        if extra:
            return _SKIP_DIRS | frozenset(extra)
    except Exception:  # pylint: disable=broad-except
        pass
    return _SKIP_DIRS


def _effective_max_file_bytes() -> int:
    """Return max file bytes from config, or module default."""
    try:
        with open(get_path("config.json"), encoding="utf-8") as _f:
            _cfg = json.load(_f)
        return int(_cfg.get("indexing", {}).get("max_file_bytes", _MAX_FILE_BYTES))
    except Exception:  # pylint: disable=broad-except
        return _MAX_FILE_BYTES

# tree-sitter node types that represent named functions / methods
_TS_FUNCTION_TYPES = frozenset({
    "function_definition",        # Python, C++
    "function_declaration",       # JS, TS, Java, Go, C
    "function_item",              # Rust
    "method_declaration",         # Java, C#
    "method_definition",          # JS/TS class methods
    "function_expression",        # JS assigned function
    "method_signature",           # TS interface methods
})

# tree-sitter node types that represent named classes / types
_TS_CLASS_TYPES = frozenset({
    "class_definition",           # Python
    "class_declaration",          # Java, JS, TS
    "abstract_class_declaration", # TypeScript abstract classes
    "class_specifier",            # C++
    "struct_item",                # Rust
    "interface_declaration",      # Java, TS
    "type_alias_declaration",     # TypeScript type aliases
    "enum_declaration",           # TypeScript / Java enums
})


# ── utility ───────────────────────────────────────────────────────────────────

def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _git_head(repo_root: str | None = None) -> str:
    """Return the current git HEAD SHA, or 'unknown' if not in a git repo."""
    try:
        cmd = ["git", "rev-parse", "HEAD"]
        if repo_root:
            cmd = ["git", "-C", repo_root, "rev-parse", "HEAD"]
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:  # pylint: disable=broad-except
        return "unknown"


def _sha256_file(path: str) -> str:
    """Return SHA-256 hex digest of a file, or empty string if file absent."""
    if not os.path.exists(path):
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_manifest(repo_root: str | None = None, symbol_count: int = 0, file_count: int = 0) -> None:
    """
    Write .cognirepo/index/manifest.json after a successful index run.

    The manifest ties the index state to a git commit SHA and records
    platform metadata so architecture mismatches can be detected on load.
    Run `cognirepo verify-index` to check integrity at any time.
    """
    manifest = {
        "git_commit": _git_head(repo_root),
        "indexed_at": _now(),
        "cognirepo_version": _cognirepo_version(),
        "platform": {
            "arch": platform.machine(),
            "python": platform.python_version(),
            "faiss": faiss.__version__,
        },
        "index_checksums": {
            "ast_index.json": _sha256_file(_ast_index_file()),
            "ast.index":      _sha256_file(_ast_faiss_file()),
            "ast_metadata.json": _sha256_file(_ast_meta_file()),
        },
        "source_file_count": file_count,
        "symbol_count": symbol_count,
    }
    try:
        with open(_manifest_file(), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
    except OSError as exc:
        log.warning("Could not write index manifest: %s", exc)


def _cognirepo_version() -> str:
    try:
        from importlib.metadata import version  # pylint: disable=import-outside-toplevel
        return version("cognirepo")
    except Exception:  # pylint: disable=broad-except
        return "dev"


def _check_platform_compat(manifest: dict) -> bool:
    """
    Return False if the index was built on a different arch or FAISS version.
    A False result means the binary index is likely unusable on this machine.
    """
    recorded = manifest.get("platform", {})
    return (
        recorded.get("arch", "") == platform.machine()
        and recorded.get("faiss", "") == faiss.__version__
    )


# ── word reverse-index helpers ────────────────────────────────────────────────

_STOP_WORDS: frozenset[str] = frozenset({
    "the", "and", "for", "with", "from", "that", "this", "into", "are",
    "not", "has", "was", "its", "use", "used", "using", "can", "will",
    "when", "then", "else", "pass", "none", "true", "false", "self",
    "cls", "args", "kwargs", "def", "class", "return", "import",
    "raise", "yield", "async", "await", "lambda",
})

_PYTHON_BUILTINS: frozenset[str] = frozenset({
    "int", "str", "list", "dict", "set", "tuple", "bool", "float",
    "bytes", "type", "len", "range", "print", "input", "open",
    "super", "object", "property", "staticmethod", "classmethod",
    "isinstance", "issubclass", "hasattr", "getattr", "setattr",
    "enumerate", "zip", "map", "filter", "sorted", "reversed",
    "min", "max", "sum", "abs", "round", "any", "all", "next", "iter",
})

import re as _re_tok  # pylint: disable=wrong-import-position


def _tokenize_identifier(name: str) -> list[str]:
    """Split camelCase / snake_case / PascalCase identifiers into lowercase tokens."""
    # Insert boundary before uppercase letters (camelCase / PascalCase)
    spaced = _re_tok.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    # Split on underscores, hyphens, dots, digits
    parts = _re_tok.split(r"[_\-\.\d\s]+", spaced)
    return [p.lower() for p in parts if len(p) >= 3]


def _tokenize_text(text: str) -> list[str]:
    """Tokenize free-form text (docstring / comment / identifier) into filtered words."""
    # Split on whitespace + punctuation
    raw = _re_tok.split(r"[\s\.,;:\"'()\[\]{}<>|=+\-*/%@!?\\`~^&]+", text)
    tokens: list[str] = []
    for tok in raw:
        for word in _tokenize_identifier(tok) or ([tok.lower()] if len(tok) >= 3 else []):
            if (
                len(word) >= 3
                and word not in _STOP_WORDS
                and word not in _PYTHON_BUILTINS
                and word.isalpha()
            ):
                tokens.append(word)
    return tokens


# ── semantic edge purpose extraction ─────────────────────────────────────────

# Verb prefixes that hint at the call's purpose
_PURPOSE_VERBS: dict[str, str] = {
    "get": "fetches", "fetch": "fetches", "load": "loads", "read": "reads",
    "set": "sets", "put": "stores", "save": "saves", "write": "writes",
    "store": "stores", "cache": "caches",
    "validate": "validates", "verify": "verifies", "check": "checks",
    "assert": "asserts", "ensure": "ensures",
    "send": "sends", "emit": "emits", "publish": "publishes", "notify": "notifies",
    "log": "logs", "record": "records", "track": "tracks",
    "parse": "parses", "decode": "decodes", "encode": "encodes",
    "build": "builds", "create": "creates", "make": "makes", "init": "initializes",
    "update": "updates", "patch": "patches", "merge": "merges",
    "delete": "deletes", "remove": "removes", "clean": "cleans",
    "handle": "handles", "process": "processes", "run": "runs",
    "start": "starts", "stop": "stops", "close": "closes",
    "convert": "converts", "transform": "transforms", "format": "formats",
    "extract": "extracts", "filter": "filters", "sort": "sorts",
    "compute": "computes", "calculate": "calculates",
}


def _extract_call_purpose(callee_name: str, caller_doc: str = "") -> str:
    """Infer a human-readable purpose label for a caller→callee edge.

    Strategy (in order):
    1. Check caller docstring for the callee name + surrounding context
    2. Match callee name's leading verb against _PURPOSE_VERBS
    3. Default: "calls"
    """
    # Docstring hint: look for "call[s] X to <purpose>" patterns
    if caller_doc and callee_name in caller_doc:
        import re as _r  # pylint: disable=import-outside-toplevel
        m = _r.search(
            rf"\b{_r.escape(callee_name)}\b.*?\bto\s+(\w+)", caller_doc, _r.IGNORECASE
        )
        if m:
            verb = m.group(1).lower()
            if verb in _PURPOSE_VERBS:
                return _PURPOSE_VERBS[verb]
            if len(verb) >= 4:
                return verb  # use the raw verb from docstring

    # Verb prefix from callee name (snake_case or camelCase)
    parts = _re_tok.split(r"[_]", callee_name)
    if parts:
        leading = parts[0].lower()
        if leading in _PURPOSE_VERBS:
            return _PURPOSE_VERBS[leading]
        # camelCase fallback: get_TokenX → "get"
        cam = _re_tok.match(r"[a-z]+", callee_name)
        if cam:
            verb = cam.group(0).lower()
            if verb in _PURPOSE_VERBS:
                return _PURPOSE_VERBS[verb]

    return "calls"


# ── tree-sitter extraction helpers ────────────────────────────────────────────

def _ts_text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")


def _ts_docstring(node, source: bytes, ext: str) -> str:
    """Extract docstring from a function/class node (Python tree-sitter only)."""
    if lang_name(ext) != "python":
        return ""
    body = node.child_by_field_name("body")
    if body is None:
        return ""
    for child in body.children:
        if child.type == "expression_statement":
            for sub in child.children:
                if sub.type in ("string", "concatenated_string"):
                    raw = _ts_text(sub, source).strip("\"'").strip()
                    return raw[:300]
            break
    return ""


def _ts_collect_calls(node, source: bytes, out: list, depth: int = 0) -> None:
    """Recursively collect function-call names from a tree-sitter subtree."""
    if depth > 12:
        return
    if node.type == "call":          # Python
        fn = node.child_by_field_name("function")
        if fn:
            attr = fn.child_by_field_name("attribute")
            if attr:
                out.append(_ts_text(attr, source))
            elif fn.type == "identifier":
                out.append(_ts_text(fn, source))
    elif node.type == "call_expression":  # JS / Java / Go
        fn = (
            node.child_by_field_name("function")
            or node.child_by_field_name("name")
        )
        if fn:
            prop = fn.child_by_field_name("property")
            name_node = prop if prop else fn
            if name_node.type in ("identifier", "property_identifier", "field_identifier"):
                out.append(_ts_text(name_node, source))
    elif node.type == "method_invocation":  # Java
        name_node = node.child_by_field_name("name")
        if name_node:
            out.append(_ts_text(name_node, source))
    for child in node.children:
        _ts_collect_calls(child, source, out, depth + 1)


def _walk_ts(node, source: bytes, ext: str, out: list) -> None:
    """Walk a tree-sitter tree and append symbol dicts to *out*."""
    if node.type in _TS_FUNCTION_TYPES:
        name_node = node.child_by_field_name("name")
        if name_node:
            calls: list[str] = []
            _ts_collect_calls(node, source, calls)
            out.append({
                "name": _ts_text(name_node, source),
                "type": "FUNCTION",
                "start_line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "docstring": _ts_docstring(node, source, ext),
                "calls": list(dict.fromkeys(calls)),
                "faiss_id": -1,
            })
    elif node.type in _TS_CLASS_TYPES:
        name_node = node.child_by_field_name("name")
        if name_node:
            out.append({
                "name": _ts_text(name_node, source),
                "type": "CLASS",
                "start_line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "docstring": "",
                "calls": [],
                "faiss_id": -1,
            })
    for child in node.children:
        _walk_ts(child, source, ext, out)


def _extract_symbols_ts(tree, source: bytes, ext: str) -> list[dict]:
    """Extract symbols from a tree-sitter parse tree."""
    out: list[dict] = []
    _walk_ts(tree.root_node, source, ext, out)
    out.sort(key=lambda s: s["start_line"])
    return out


# ── stdlib-ast extraction (Python fallback) ───────────────────────────────────

def _extract_decorators(node: ast.AST) -> list[str]:
    """Extract decorator text from a function/class node."""
    decorators: list[str] = []
    for dec in getattr(node, "decorator_list", []):
        try:
            if hasattr(ast, "unparse"):
                decorators.append(ast.unparse(dec))
            elif isinstance(dec, ast.Call):
                func_part = ""
                if isinstance(dec.func, ast.Attribute):
                    func_part = dec.func.attr
                elif isinstance(dec.func, ast.Name):
                    func_part = dec.func.id
                arg_part = ""
                if dec.args:
                    a = dec.args[0]
                    if isinstance(a, ast.Constant):
                        arg_part = repr(a.value)
                decorators.append(f"{func_part}({arg_part})" if arg_part else func_part)
            elif isinstance(dec, ast.Attribute):
                decorators.append(dec.attr)
            elif isinstance(dec, ast.Name):
                decorators.append(dec.id)
        except Exception:  # pylint: disable=broad-except
            pass
    return decorators


def _extract_calls(node: ast.AST) -> list[str]:
    """Extract called function names from a node."""
    calls: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                calls.append(func.id)
            elif isinstance(func, ast.Attribute):
                calls.append(func.attr)
    return list(dict.fromkeys(calls))


def _dynamic_dispatch_tags(node: ast.AST) -> list[str]:
    """
    Detect dynamic registration patterns:
    scheduler.add_job(fn_name, ...) → extract fn_name as a dynamic caller edge.
    Returns list of function names registered dynamically.
    """
    _DISPATCHER_NAMES = frozenset({
        "add_job", "add_task", "connect", "register", "on", "handler",
        "task", "route", "signal_connect", "subscribe", "listen",
    })
    registered: list[str] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        # Check if the call is a known dispatcher
        func = child.func
        func_name = ""
        if isinstance(func, ast.Attribute):
            func_name = func.attr
        elif isinstance(func, ast.Name):
            func_name = func.id
        if func_name not in _DISPATCHER_NAMES:
            continue
        # Extract first positional argument if it's a Name (function reference)
        for arg in child.args:
            if isinstance(arg, ast.Name):
                registered.append(arg.id)
            elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                registered.append(arg.value)
    return list(dict.fromkeys(registered))


def _extract_symbols_py(tree: ast.AST, _file_path: str) -> list[dict]:
    """
    Walk a Python stdlib AST and collect:
    - FunctionDef / AsyncFunctionDef (including dunders, properties)
    - ClassDef
    - Module/class-level assignments → CONSTANT / VARIABLE
    - Annotated assignments → TYPED_FIELD
    - Lambda assignments → LAMBDA

    Used when tree-sitter-python is not installed.
    """
    symbols: list[dict] = []

    # ── 1. functions and classes ───────────────────────────────────────────────
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sym_type = "FUNCTION"
            decorators = _extract_decorators(node)

            # Tag special function variants
            tags: list[str] = []
            for dec in decorators:
                if dec in ("property", "property.setter", "property.deleter"):
                    tags.append("property")
                elif dec == "staticmethod":
                    tags.append("staticmethod")
                elif dec == "classmethod":
                    tags.append("classmethod")
            if node.name.startswith("__") and node.name.endswith("__"):
                tags.append("dunder")

            docstring = ast.get_docstring(node) or ""
            end_line = getattr(node, "end_lineno", node.lineno)
            calls = _extract_calls(node)

            # Dynamic dispatch detection: find functions registered via add_job etc.
            dyn_targets = _dynamic_dispatch_tags(node)

            symbols.append({
                "name": node.name,
                "type": sym_type,
                "start_line": node.lineno,
                "end_line": end_line,
                "docstring": docstring[:300],
                "calls": calls,
                "decorators": decorators,
                "tags": tags,
                "dynamic_registers": dyn_targets,
                "faiss_id": -1,
            })

        elif isinstance(node, ast.ClassDef):
            docstring = ast.get_docstring(node) or ""
            end_line = getattr(node, "end_lineno", node.lineno)
            symbols.append({
                "name": node.name,
                "type": "CLASS",
                "start_line": node.lineno,
                "end_line": end_line,
                "docstring": docstring[:300],
                "calls": [],
                "decorators": _extract_decorators(node),
                "tags": [],
                "dynamic_registers": [],
                "faiss_id": -1,
            })

    # ── 2. module / class-level assignments → CONSTANT / VARIABLE ────────────
    # We only want top-level and class-body assignments, not local variables
    def _collect_assignments(body_nodes: list) -> None:
        for node in body_nodes:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        name = target.id
                        # Skip private double-underscore vars and temp names
                        if name.startswith("__") and name.endswith("__"):
                            continue
                        sym_type = "CONSTANT" if name.isupper() else "VARIABLE"
                        # Try to extract value as string
                        val_str = ""
                        try:
                            if hasattr(ast, "unparse"):
                                val_str = ast.unparse(node.value)[:80]
                        except Exception:  # pylint: disable=broad-except
                            pass
                        symbols.append({
                            "name": name,
                            "type": sym_type,
                            "start_line": node.lineno,
                            "end_line": getattr(node, "end_lineno", node.lineno),
                            "docstring": val_str,
                            "calls": [],
                            "decorators": [],
                            "tags": [],
                            "dynamic_registers": [],
                            "faiss_id": -1,
                        })
                    elif isinstance(target, ast.Name):
                        pass
                    # Lambda assignments: x = lambda ...:
                    if (len(node.targets) == 1 and
                            isinstance(node.targets[0], ast.Name) and
                            isinstance(node.value, ast.Lambda)):
                        lname = node.targets[0].id
                        symbols.append({
                            "name": lname,
                            "type": "LAMBDA",
                            "start_line": node.lineno,
                            "end_line": getattr(node, "end_lineno", node.lineno),
                            "docstring": "",
                            "calls": _extract_calls(node.value),
                            "decorators": [],
                            "tags": ["lambda"],
                            "dynamic_registers": [],
                            "faiss_id": -1,
                        })

            elif isinstance(node, ast.AnnAssign):
                # Typed class fields: name: Type = value
                if isinstance(node.target, ast.Name):
                    name = node.target.id
                    ann_str = ""
                    try:
                        if hasattr(ast, "unparse"):
                            ann_str = ast.unparse(node.annotation)[:60]
                    except Exception:  # pylint: disable=broad-except
                        pass
                    symbols.append({
                        "name": name,
                        "type": "TYPED_FIELD",
                        "start_line": node.lineno,
                        "end_line": getattr(node, "end_lineno", node.lineno),
                        "docstring": f"type: {ann_str}",
                        "calls": [],
                        "decorators": [],
                        "tags": ["typed_field"],
                        "dynamic_registers": [],
                        "faiss_id": -1,
                    })

            elif isinstance(node, ast.ClassDef):
                # Recurse into class body for class-level assignments
                _collect_assignments(node.body)

    _collect_assignments(getattr(tree, "body", []))

    # Deduplicate by (name, start_line) — lambda check above may produce duplicates
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for sym in symbols:
        key = (sym["name"], sym["start_line"])
        if key not in seen:
            seen.add(key)
            deduped.append(sym)

    deduped.sort(key=lambda s: s["start_line"])
    return deduped


# ── main indexer class ────────────────────────────────────────────────────────

def _find_entry_points(tracked: "set[str]") -> "list[str]":
    """Return likely entry-point files from the tracked set, ordered by priority."""
    priority = [
        "__main__.py", "main.py", "app.py", "manage.py",
        "run.py", "server.py", "cli.py", "start.py", "wsgi.py", "asgi.py",
    ]
    found = []
    for name in priority:
        for f in sorted(tracked):
            if Path(f).name == name:
                found.append(f)
    # Fallback: top-level .py files
    if not found:
        found = [f for f in sorted(tracked) if "/" not in f and f.endswith(".py")]
    return found


def _expand_from_entry_points(
    entry_points: "list[str]",
    tracked: "set[str]",
    repo_root: str,
) -> "set[str]":
    """BFS from entry points following Python imports within the tracked file set."""
    import ast as _ast  # local to avoid polluting module namespace

    # Map: dotted-module-path → rel_file_path for all tracked .py files
    py_files = {f for f in tracked if f.endswith(".py")}
    module_map: "dict[str, str]" = {}
    for f in py_files:
        parts = Path(f).with_suffix("").parts
        module_map[".".join(parts)] = f
        # Also map without trailing __init__
        if parts and parts[-1] == "__init__":
            module_map[".".join(parts[:-1])] = f

    def _resolve(module: str, current_file: str) -> "list[str]":
        """Try to resolve an import module name to a tracked rel path."""
        candidates = []
        # absolute import
        if module in module_map:
            candidates.append(module_map[module])
        # parent package prefix (e.g. "cognirepo.cli" matches "cognirepo/cli.py")
        for key, val in module_map.items():
            if key == module or key.startswith(module + "."):
                candidates.append(val)
                break
        return candidates

    visited: "set[str]" = set(entry_points)
    queue = list(entry_points)
    while queue:
        current = queue.pop(0)
        abs_path = os.path.join(repo_root, current)
        if not os.path.isfile(abs_path):
            continue
        try:
            source = Path(abs_path).read_bytes()
            tree = _ast.parse(source.decode("utf-8", errors="ignore"), filename=abs_path)
        except (SyntaxError, Exception):  # pylint: disable=broad-except
            continue
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Import):
                for alias in node.names:
                    for target in _resolve(alias.name, current):
                        if target not in visited:
                            visited.add(target)
                            queue.append(target)
            elif isinstance(node, _ast.ImportFrom):
                if node.module and node.level == 0:
                    for target in _resolve(node.module, current):
                        if target not in visited:
                            visited.add(target)
                            queue.append(target)
                elif node.module and node.level > 0:
                    # relative import — resolve from current package
                    pkg_parts = Path(current).parent.parts
                    if node.level <= len(pkg_parts):
                        base = ".".join(pkg_parts[: len(pkg_parts) - node.level + 1])
                        full = f"{base}.{node.module}" if base else node.module
                        for target in _resolve(full, current):
                            if target not in visited:
                                visited.add(target)
                                queue.append(target)
    return visited


def _git_tracked_files(repo_root: str) -> "set[str] | None":
    try:
        proc = subprocess.run(
            ["git", "-C", repo_root, "ls-files", "--recurse-submodules"],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    paths = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    return paths if paths else None


class ASTIndexer:
    """
    Index a multi-language repo: extract symbols → embed → FAISS + reverse index.

    Supported languages depend on installed grammar packages
    (pip install cognirepo[languages]).  Python is always supported via
    the stdlib-ast fallback even without the tree-sitter-python grammar.
    """

    def __init__(self, graph: KnowledgeGraph) -> None:
        self.graph = graph
        self.model = get_model()
        self.faiss_index: faiss.Index | None = None
        self.faiss_meta: list[dict] = []
        self.index_data: dict = {
            "version": 2,
            "indexed_at": _now(),
            "repo_root": "",
            "files": {},
            "reverse_index": {},
            "word_reverse_index": {},
            "faiss_index_file": _ast_faiss_file(),
            "total_symbols": 0,
        }
        self._loaded = False

    # ── FAISS lifecycle ───────────────────────────────────────────────────────

    def _ensure_faiss(self) -> None:
        if self.faiss_index is None:
            inner = faiss.IndexFlatL2(384)
            self.faiss_index = faiss.IndexIDMap2(inner)

    # ── parsing dispatch ──────────────────────────────────────────────────────

    def _parse_file(self, abs_path: str, ext: str) -> list[dict]:
        """
        Parse one file and return raw symbol dicts.

        Strategy:
          1. Try tree-sitter (if grammar available for this extension).
          2. Fall back to stdlib ast for Python files.
          3. Return [] for anything else.
        """
        source = Path(abs_path).read_bytes()
        lang = _get_language(ext)

        if lang is not None:
            try:
                from tree_sitter import Parser  # pylint: disable=import-outside-toplevel
                parser = Parser(lang)
                tree = parser.parse(source)
                return _extract_symbols_ts(tree, source, ext)
            except Exception as exc:  # pylint: disable=broad-except
                log.debug("tree-sitter parse failed for %s: %s", abs_path, exc)
                if ext != ".py":
                    return []
                # fall through to stdlib ast for Python

        if ext == ".py":
            try:
                tree_py = ast.parse(
                    source.decode("utf-8", errors="ignore"),
                    filename=abs_path,
                )
                return _extract_symbols_py(tree_py, abs_path)
            except SyntaxError:
                return []

        return []

    # ── public API ────────────────────────────────────────────────────────────

    def index_repo(self, repo_root: str, embed: bool = True) -> dict:
        """
        Walk *repo_root*, index every supported file (skipping _SKIP_DIRS),
        build the reverse index, and save everything to disk.
        Returns a summary dict with per-language file counts.

        Parameters
        ----------
        embed : If False, skip FAISS embedding (AST/symbol index + graph only).
                Faster for CI or when only symbol lookup is needed.
        """
        self._embed_enabled = embed  # pylint: disable=attribute-defined-outside-init
        self._ensure_faiss()
        repo_root = os.path.abspath(repo_root)
        self.index_data["repo_root"] = repo_root
        self.index_data["indexed_at"] = _now()

        skip_dirs = _effective_skip_dirs()

        # ── git-first + entry-point file discovery ──────────────────────────────
        _git_root = os.path.join(repo_root, ".git")
        _tracked: "set[str] | None" = None
        if os.path.exists(_git_root):
            _tracked = _git_tracked_files(repo_root)
            if _tracked is not None:
                _entries = _find_entry_points(_tracked)
                if _entries:
                    _reachable = _expand_from_entry_points(_entries, _tracked, repo_root)
                    _non_py = {f for f in _tracked if not f.endswith(".py")}
                    _tracked = _reachable | _non_py
                    print(
                        f"  Git repo + entry-point traversal: {len(_tracked)} file(s) "
                        f"reachable from {len(_entries)} entry point(s) "
                        f"({', '.join(Path(e).name for e in _entries[:3])}"
                        f"{'...' if len(_entries) > 3 else ''})"
                    )
                else:
                    print(f"  Git repo detected — indexing {len(_tracked)} tracked file(s).")

        # ── large-repo warning (embed pass only) ────────────────────────────────
        if embed:
            if _tracked is not None:
                _n_candidates = sum(1 for f in _tracked if is_supported(Path(f)))
            else:
                _n_candidates = 0
                for _dp, _dns, _fns in os.walk(repo_root):
                    _dns[:] = [d for d in _dns if d not in skip_dirs]
                    _n_candidates += sum(1 for f in _fns if is_supported(Path(f)))
            if _n_candidates > _LARGE_REPO_FILE_THRESHOLD:
                print(
                    f"  ⚠  Large repo detected ({_n_candidates} source files). "
                    "First-run tip: use --no-embed for a faster symbol-only index, "
                    "then run index-repo again to add embeddings."
                )

        lang_file_counts: dict[str, int] = defaultdict(int)
        skipped_exts: set[str] = set()
        total_files = 0

        _skip_noise = {
            ".md", ".txt", ".json", ".yaml", ".yml", ".toml",
            ".cfg", ".ini", ".lock", ".gitignore", ".env",
            ".png", ".jpg", ".gif", ".svg", ".ico",
            ".whl", ".zip", ".tar", ".gz",
        }

        if _tracked is not None:
            for rel_path in sorted(_tracked):
                abs_path = os.path.join(repo_root, rel_path)
                if not os.path.isfile(abs_path):
                    continue
                ext = Path(rel_path).suffix
                if not is_supported(Path(rel_path)):
                    if ext and ext not in _skip_noise:
                        skipped_exts.add(ext)
                    continue
                try:
                    self.index_file(rel_path, abs_path)
                    lang_file_counts[lang_label(ext)] += 1
                    total_files += 1
                except Exception as exc:  # pylint: disable=broad-except
                    log.debug("  [skip] %s: %s", rel_path, exc)
        else:
            for dirpath, dirnames, filenames in os.walk(repo_root):
                dirnames[:] = [d for d in dirnames if d not in skip_dirs]
                for fname in filenames:
                    ext = Path(fname).suffix
                    if not is_supported(Path(fname)):
                        if ext and ext not in _skip_noise:
                            skipped_exts.add(ext)
                        continue
                    abs_path = os.path.join(dirpath, fname)
                    rel_path = os.path.relpath(abs_path, repo_root)
                    try:
                        self.index_file(rel_path, abs_path)
                        lang_file_counts[lang_label(ext)] += 1
                        total_files += 1
                    except Exception as exc:  # pylint: disable=broad-except
                        log.debug("  [skip] %s: %s", rel_path, exc)

        self._build_reverse_index()
        total_symbols = sum(
            len(f.get("symbols", [])) for f in self.index_data["files"].values()
        )
        self.index_data["total_symbols"] = total_symbols
        self.save()

        # ── summary output ────────────────────────────────────────────────────
        print(f"Indexed {total_symbols} symbols across {total_files} files")
        if lang_file_counts:
            parts = " · ".join(
                f"{label}: {n} {'file' if n == 1 else 'files'}"
                for label, n in sorted(lang_file_counts.items())
            )
            print(f"  {parts}")
        if skipped_exts:
            skipped_str = ", ".join(sorted(skipped_exts))
            print(
                f"  Unsupported extensions skipped: {skipped_str} "
                f"(install cognirepo[languages])"
            )

        # ── cold-start transparency banner ────────────────────────────────────
        _print_cold_start_banner()

        return {
            "files": total_files,
            "symbols": total_symbols,
            "languages": dict(lang_file_counts),
            "skipped_extensions": sorted(skipped_exts),
        }

    def index_file(self, rel_path: str, abs_path: str | None = None) -> dict:
        """
        Index one file. Skips if sha256 matches existing entry or file > max_file_bytes.
        Returns the file record dict.
        """
        ext = Path(rel_path).suffix
        if not is_supported(Path(rel_path)):
            return {}

        self._ensure_faiss()
        if abs_path is None:
            abs_path = rel_path

        # ── per-file size guard (T7) ──────────────────────────────────────────
        try:
            if os.path.getsize(abs_path) > _effective_max_file_bytes():
                log.debug("[skip-large] %s exceeds max_file_bytes limit", rel_path)
                return {}
        except OSError:
            pass

        sha = _sha256(abs_path)
        existing = self.index_data["files"].get(rel_path, {})
        if existing.get("sha256") == sha:
            return existing  # unchanged — skip

        raw_symbols = self._parse_file(abs_path, ext)

        # remove old FAISS entries for this file
        old_ids = [
            s["faiss_id"] for s in existing.get("symbols", [])
            if s.get("faiss_id", -1) >= 0
        ]
        if old_ids and self.faiss_index is not None:
            try:
                self.faiss_index.remove_ids(np.array(old_ids, dtype=np.int64))
            except Exception:  # pylint: disable=broad-except
                pass

        # embed + add to FAISS (skipped when embed=False / --no-embed)
        embed_enabled = getattr(self, "_embed_enabled", True)

        # Pre-read source lines once per file for body-snippet enrichment
        _src_lines: list[str] = []
        if embed_enabled:
            try:
                with open(abs_path, encoding="utf-8", errors="replace") as _sf:
                    _src_lines = _sf.readlines()
            except OSError:
                pass

        for sym in raw_symbols:
            if embed_enabled:
                # Enriched embed text: type + name + decorators + docstring +
                # first 3 body lines (signature context) + top callees
                dec_str = " ".join(sym.get("decorators", []))
                calls_str = ", ".join(sym.get("calls", [])[:3])
                # Extract first 3 lines after the definition line for signature/body context
                body_snippet = ""
                if _src_lines and sym["type"] in ("FUNCTION", "CLASS"):
                    start = sym.get("start_line", 1)
                    end = min(start + 3, sym.get("end_line", start + 3))
                    snippet_lines = _src_lines[start - 1 : end]  # 0-indexed
                    body_snippet = " ".join(l.strip() for l in snippet_lines if l.strip())[:200]
                embed_text = " ".join(filter(None, [
                    sym["type"],
                    sym["name"],
                    dec_str,
                    sym.get("docstring", ""),
                    body_snippet,
                    f"calls: {calls_str}" if calls_str else "",
                ]))
                vec = self.model.encode(embed_text).astype("float32")
                faiss_id = len(self.faiss_meta)
                self.faiss_index.add_with_ids(
                    np.array([vec], dtype="float32"),
                    np.array([faiss_id], dtype=np.int64),
                )
                self.faiss_meta.append({
                    "name": sym["name"],
                    "type": sym["type"],
                    "file": rel_path,
                    "start_line": sym["start_line"],
                    "docstring": sym.get("docstring", ""),
                    "decorators": sym.get("decorators", []),
                    "source": "symbol",
                })
                sym["faiss_id"] = faiss_id
            else:
                sym["faiss_id"] = -1  # not embedded

            # knowledge graph
            file_node = make_node_id("FILE", rel_path)
            sym_node = node_id_from_symbol_record(sym, rel_path)
            self.graph.add_node(file_node, NodeType.FILE)
            self.graph.add_node(sym_node, sym["type"], file=rel_path, line=sym["start_line"])
            self.graph.add_edge(sym_node, file_node, EdgeType.DEFINED_IN)

        # ── file-level summary embedding ──────────────────────────────────────
        # Enables "what does background_tasks.py do?" queries to land in FAISS
        # even when no individual symbol name matches the query.
        if embed_enabled and raw_symbols:
            fn_names = [s["name"] for s in raw_symbols if s["type"] == "FUNCTION"][:8]
            cls_names = [s["name"] for s in raw_symbols if s["type"] == "CLASS"][:4]
            # Use docstring from first module-level function/class if available
            _first_doc = next(
                (s.get("docstring", "") for s in raw_symbols
                 if s.get("docstring") and s["type"] in ("FUNCTION", "CLASS")),
                "",
            )
            file_embed_text = " ".join(filter(None, [
                "FILE",
                os.path.basename(rel_path),
                os.path.splitext(os.path.basename(rel_path))[0].replace("_", " "),
                _first_doc[:120] if _first_doc else "",
                f"functions: {', '.join(fn_names)}" if fn_names else "",
                f"classes: {', '.join(cls_names)}" if cls_names else "",
            ]))
            try:
                _fvec = self.model.encode(file_embed_text).astype("float32")
                _fid = len(self.faiss_meta)
                self.faiss_index.add_with_ids(
                    np.array([_fvec], dtype="float32"),
                    np.array([_fid], dtype=np.int64),
                )
                self.faiss_meta.append({
                    "name": os.path.basename(rel_path),
                    "type": "FILE",
                    "file": rel_path,
                    "start_line": 1,
                    "docstring": _first_doc[:120],
                    "source": "file_summary",
                })
            except Exception:  # pylint: disable=broad-except
                pass  # file summary embedding is best-effort

        # call-graph edges — bidirectional, with semantic purpose labels
        for sym in raw_symbols:
            caller_node = node_id_from_symbol_record(sym, rel_path)
            caller_doc = sym.get("docstring", "") or ""
            for callee_name in sym.get("calls", []):
                callee_node = f"symbol::{callee_name}"
                purpose = _extract_call_purpose(callee_name, caller_doc)
                self.graph.add_node(callee_node, NodeType.CONCEPT)
                self.graph.add_edge(caller_node, callee_node, EdgeType.CALLED_BY, purpose=purpose)
                self.graph.add_edge(callee_node, caller_node, EdgeType.CALLS)

        file_record = {
            "indexed_at": _now(),
            "sha256": sha,
            "language": lang_label(ext),
            "symbols": raw_symbols,
        }
        self.index_data["files"][rel_path] = file_record

        # incrementally update reverse_index for this file only
        rev = self.index_data.setdefault("reverse_index", {})
        # remove old entries pointing to this file
        for name, locations in list(rev.items()):
            rev[name] = [loc for loc in locations if loc[0] != rel_path]
            if not rev[name]:
                del rev[name]
        # add new entries
        for sym in raw_symbols:
            entry = [rel_path, sym["start_line"]]
            rev.setdefault(sym["name"], [])
            if entry not in rev[sym["name"]]:
                rev[sym["name"]].append(entry)
        # incrementally update word_reverse_index for this file
        wrev = self.index_data.setdefault("word_reverse_index", {})
        for word, locs in list(wrev.items()):
            wrev[word] = [loc for loc in locs if loc[0] != rel_path]
            if not wrev[word]:
                del wrev[word]
        for sym in raw_symbols:
            line = sym["start_line"]
            for text in [sym.get("name", ""), sym.get("docstring", "") or "", sym.get("inline_comment", "") or ""]:
                for word in _tokenize_text(text):
                    entry = [rel_path, line]
                    wrev.setdefault(word, [])
                    if entry not in wrev[word]:
                        wrev[word].append(entry)

        # invalidate lookup caches so stale results are not served
        type(self).lookup_symbol.cache_clear()
        type(self).lookup_word.cache_clear()

        return file_record

    # ── kept for ASTIndexer API compatibility ─────────────────────────────────

    def _extract_symbols(self, tree: ast.AST, file_path: str) -> list[dict]:
        """Stdlib-ast extraction (kept for backward compat with callers)."""
        return _extract_symbols_py(tree, file_path)

    def _build_reverse_index(self) -> None:
        """Build reverse_index: symbol_name → [[file, line], ...]."""
        rev: dict[str, list] = {}
        for file_path, file_data in self.index_data["files"].items():
            for sym in file_data.get("symbols", []):
                name = sym["name"]
                entry = [file_path, sym["start_line"]]
                rev.setdefault(name, [])
                if entry not in rev[name]:
                    rev[name].append(entry)
        self.index_data["reverse_index"] = rev
        # Build word reverse index from all symbols
        self._build_word_reverse_index()
        # invalidate lookup cache so fresh results are served
        type(self).lookup_symbol.cache_clear()
        type(self).lookup_word.cache_clear()

    def _build_word_reverse_index(self) -> None:
        """Build word_reverse_index: word → [[file, line], ...].

        Tokenizes all symbol names, docstrings, and inline comments so
        that non-symbol words (e.g. 'background', 'validate') are findable
        even when they aren't standalone function/class names.

        Token extraction:
          - camelCase → ["camel", "case"]
          - snake_case → ["snake", "case"]
          - docstring words (first 200 chars)
          - inline comment words

        Filtered: stop-words, words < 3 chars, Python builtins.
        """
        import re as _re  # pylint: disable=import-outside-toplevel
        word_idx: dict[str, list] = {}

        for file_path, file_data in self.index_data["files"].items():
            for sym in file_data.get("symbols", []):
                line = sym["start_line"]
                name = sym.get("name", "")
                doc = sym.get("docstring", "") or ""
                comment = sym.get("inline_comment", "") or ""

                # Collect all text sources for this symbol
                sources = [name, doc[:200], comment[:120]]
                for text in sources:
                    for word in _tokenize_text(text):
                        entry = [file_path, line]
                        word_idx.setdefault(word, [])
                        if entry not in word_idx[word]:
                            word_idx[word].append(entry)

        self.index_data["word_reverse_index"] = word_idx

    # ── lookup ────────────────────────────────────────────────────────────────

    @functools.lru_cache(maxsize=512)
    def lookup_symbol(self, symbol_name: str) -> list[dict]:
        """O(1) reverse-index lookup. Returns [{'file': str, 'line': int}]."""
        entries = self.index_data["reverse_index"].get(symbol_name, [])
        return [{"file": f, "line": l} for f, l in entries]

    @functools.lru_cache(maxsize=512)
    def lookup_word(self, word: str) -> list[dict]:
        """Word-level reverse-index lookup.

        Returns [{'file': str, 'line': int}] for all occurrences of *word*
        in symbol names, docstrings, and inline comments.  Sorted by
        file path for deterministic output.

        Falls back to lookup_symbol() if no word-index entry found, so
        callers can use this as the single lookup entry point.
        """
        word_lower = word.lower()
        entries = self.index_data.get("word_reverse_index", {}).get(word_lower, [])
        if not entries:
            # fallback: exact symbol name match
            return self.lookup_symbol(word)
        results = [{"file": f, "line": l} for f, l in entries]
        results.sort(key=lambda x: x["file"])
        return results

    def get_symbol_table(self, file_path: str) -> SymbolTable:
        """Return a SymbolTable for bisect-based line-range queries."""
        return build_symbol_table_from_index(file_path, self.index_data)

    # ── persistence ───────────────────────────────────────────────────────────

    def save(self) -> None:
        """Persist AST index, FAISS index, and metadata to disk.
        Also writes manifest.json with git SHA, platform info, and checksums
        so `cognirepo verify-index` can detect staleness or corruption later.
        """
        os.makedirs(os.path.dirname(_ast_index_file()), exist_ok=True)
        with open(_ast_index_file(), "w", encoding="utf-8") as f:
            json.dump(self.index_data, f, indent=2)
        if self.faiss_index is not None:
            faiss.write_index(self.faiss_index, _ast_faiss_file())
        with open(_ast_meta_file(), "w", encoding="utf-8") as f:
            json.dump(self.faiss_meta, f, indent=2)

        # Write integrity manifest after all index files are on disk
        repo_root = self.index_data.get("repo_root") or None
        file_count = len(self.index_data.get("files", {}))
        symbol_count = self.index_data.get("total_symbols", len(self.faiss_meta))
        _write_manifest(repo_root=repo_root, symbol_count=symbol_count, file_count=file_count)

    def load(self) -> None:
        """Load existing index from disk. Silently does nothing if not present.

        Checks manifest.json for platform compatibility before loading the
        FAISS binary.  If the binary was built on a different arch or FAISS
        version, a warning is logged and the stale binary is renamed to
        .stale so it is not used.  The caller should trigger a re-index.
        """
        # Platform compat check: read manifest before loading FAISS binary
        if os.path.exists(_manifest_file()):
            try:
                with open(_manifest_file(), encoding="utf-8") as f:
                    manifest = json.load(f)
                if not _check_platform_compat(manifest):
                    recorded = manifest.get("platform", {})
                    log.warning(
                        "Index was built on %s/%s but running on %s/%s. "
                        "The FAISS binary is not portable — skipping load. "
                        "Re-run `cognirepo index-repo .` to rebuild.",
                        recorded.get("arch"), recorded.get("faiss"),
                        platform.machine(), faiss.__version__,
                    )
                    # Rename stale binary so _ensure_faiss() creates a fresh one
                    if os.path.exists(_ast_faiss_file()):
                        try:
                            os.rename(_ast_faiss_file(), _ast_faiss_file() + ".stale")
                        except OSError:
                            pass
                    self._ensure_faiss()
                    self._loaded = True
                    return
            except (OSError, json.JSONDecodeError):
                pass  # manifest absent or unreadable — proceed normally

        if os.path.exists(_ast_index_file()):
            with open(_ast_index_file(), encoding="utf-8") as f:
                self.index_data = json.load(f)
        if os.path.exists(_ast_faiss_file()):
            try:
                self.faiss_index = faiss.read_index(_ast_faiss_file())
            except Exception as exc:  # pylint: disable=broad-except
                log.warning(
                    "ast.index could not be loaded (%s). "
                    "Renaming to .stale and starting fresh. "
                    "Re-run `cognirepo index-repo .` to rebuild.",
                    exc,
                )
                try:
                    os.rename(_ast_faiss_file(), _ast_faiss_file() + ".stale")
                except OSError:
                    pass
                self._ensure_faiss()
        else:
            self._ensure_faiss()
        if os.path.exists(_ast_meta_file()):
            with open(_ast_meta_file(), encoding="utf-8") as f:
                self.faiss_meta = json.load(f)
        self._loaded = True
