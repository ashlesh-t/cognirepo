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
from typing import Any, Callable

import faiss
import numpy as np
import warnings

from data.graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType
from data.graph.graph_utils import make_node_id, node_id_from_symbol_record
from intelligence.indexer.index_utils import SymbolTable, build_symbol_table_from_index
from intelligence.indexer.language_registry import (
    _get_language,
    is_supported,
    lang_label,
    lang_name,
)
from data.memory.embeddings import get_model

log = logging.getLogger(__name__)

from core.config.paths import get_path

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
    # Go / Kubernetes
    # NOTE: "staging" is deliberately NOT skipped — in Kubernetes-style repos
    # staging/ holds real first-party source (k8s.io/apiserver etc.). Repos that
    # use staging/ as a build artifact dir can re-add it via config.json:
    #   {"indexing": {"skip_dirs": ["staging"]}}
    "vendor", "third_party", "_output", "_artifacts",
    # Bazel
    "bazel-bin", "bazel-out", "bazel-testlogs", "bazel-genfiles",
    # General build
    "dist", "build", "target", "bin",
    # CogniRepo internal
    ".cognirepo",
    # Misc generated / temp
    "tmp", "temp", "logs", ".terraform", ".serverless", "__mocks__",
    "coverage", "zz_generated",
})

# Maximum file size to index (bytes). Files larger than this are skipped.
_MAX_FILE_BYTES: int = 300_000  # 300 KB

# Threshold above which a large-repo embed warning is printed.
_LARGE_REPO_FILE_THRESHOLD: int = 3_000

# Extensions where embedding adds little value (config/data files).
# AST symbol index is still built; only FAISS embedding is skipped.
_NO_EMBED_EXTS: frozenset[str] = frozenset({".yaml", ".yml", ".sh", ".bash", ".toml", ".ini", ".cfg"})

# Above this many source files, switch to lightweight graph mode (only high-weight symbols).
# Users can override with index_repo(skip_graph=True) to disable graph entirely.
_AUTO_SKIP_GRAPH_THRESHOLD: int = 10_000

# Minimum crawl weight for a symbol to be included in the graph in lite-graph mode.
# 1.0 = direct entry-point reachable, 0.75 = hop-2 reachable, 0.5 = git-tracked indirect.
# At 0.75 only direct + hop-2 symbols appear, keeping graph to ~1k–5k nodes on large repos.
_LITE_GRAPH_WEIGHT_MIN: float = 0.75

# Tiered indexing: Tier 1 covers high-weight files (fast bootstrap for large repos).
# Tier 2 covers everything else in a background pass.
_TIER1_WEIGHT_MIN: float = 0.5    # Tier 1: all BFS-reachable files (direct + indirect imports)
_LARGE_REPO_TIER_THRESHOLD: int = _AUTO_SKIP_GRAPH_THRESHOLD  # same boundary as lite-graph



def _effective_skip_dirs() -> frozenset[str]:
    """Return _SKIP_DIRS adjusted by .cognirepo/config.json.

    config.json → "indexing": {
        "skip_dirs":   [...],   # extra dirs to skip (merged with defaults)
        "unskip_dirs": [...]    # default-skipped dirs to index anyway
    }
    """
    try:
        with open(get_path("config.json"), encoding="utf-8") as _f:
            _cfg = json.load(_f)
        _indexing = _cfg.get("indexing", {})
        extra: list[str] = _indexing.get("skip_dirs", [])
        unskip: list[str] = _indexing.get("unskip_dirs", [])
        if extra or unskip:
            return (_SKIP_DIRS | frozenset(extra)) - frozenset(unskip)
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
    "arrow_function",             # JS/TS arrow functions
    "method_signature",           # TS interface methods
    "function_signature",         # TS ambient/overload signatures
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
    "type_spec",                  # Go: type Foo struct{...} / type Bar interface{...}
                                  # (name field lives on type_spec, not type_declaration)
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
                method_name = _ts_text(name_node, source)
                out.append(method_name)
                # For Go selector_expression, also record "receiver::method" so
                # who_calls() can match type-specific receiver calls.
                if fn.type == "selector_expression":
                    obj_node = fn.child_by_field_name("operand")
                    if obj_node and obj_node.type == "identifier":
                        receiver_type = _ts_text(obj_node, source)
                        if receiver_type and receiver_type[0].isupper():
                            out.append(f"{receiver_type}::{method_name}")
    elif node.type == "method_invocation":  # Java
        name_node = node.child_by_field_name("name")
        if name_node:
            out.append(_ts_text(name_node, source))
    for child in node.children:
        _ts_collect_calls(child, source, out, depth + 1)


def _ts_decorators(parent_node, source: bytes) -> list[str]:
    """Extract decorator names from a decorated_definition parent node.

    In tree-sitter, decorators are siblings of the function/class under a
    `decorated_definition` wrapper, not children of the function node itself.
    Pass the `decorated_definition` node (or any node that may have decorator children).
    """
    decs: list[str] = []
    for child in parent_node.children:
        if child.type == "decorator":
            for sub in child.children:
                if sub.type != "@":
                    decs.append(_ts_text(sub, source).split("(")[0].strip())
                    break
    return decs


def _ts_bases(node, source: bytes) -> list[str]:
    """Extract base class names from a class tree-sitter node."""
    bases: list[str] = []
    # Python: argument_list child of class_definition
    arg_list = node.child_by_field_name("superclasses") or node.child_by_field_name("bases")
    if arg_list is None:
        # fallback: find argument_list or base_list child
        for child in node.children:
            if child.type in ("argument_list", "base_list", "type_list"):
                arg_list = child
                break
    if arg_list:
        for child in arg_list.children:
            if child.type in ("identifier", "type_identifier", "attribute"):
                name = _ts_text(child, source)
                if name not in ("object", "ABC", "Enum", "IntEnum", ",", "(", ")"):
                    bases.append(name)
    return bases


def _walk_ts(node, source: bytes, ext: str, out: list, _parent_decs: "list[str] | None" = None) -> None:
    """Walk a tree-sitter tree and append symbol dicts to *out*."""
    # `decorated_definition` wraps a decorator list + the actual function/class.
    # Collect decorators here and pass them down to the inner definition node.
    if node.type == "decorated_definition":
        decs = _ts_decorators(node, source)
        for child in node.children:
            if child.type not in ("decorator",):
                _walk_ts(child, source, ext, out, _parent_decs=decs)
        return

    if node.type in _TS_FUNCTION_TYPES:
        name_node = node.child_by_field_name("name")
        # arrow functions assigned to a variable: capture parent's name via caller
        if name_node is None and node.type == "arrow_function":
            for child in node.children:
                _walk_ts(child, source, ext, out)
            return
        if name_node:
            calls: list[str] = []
            _ts_collect_calls(node, source, calls)
            out.append({
                "name": _ts_text(name_node, source),
                "type": "FUNCTION",
                "start_line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "docstring": _ts_docstring(node, source, ext),
                "decorators": _parent_decs or [],
                "tags": [],
                "calls": list(dict.fromkeys(calls)),
                "bases": [],
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
                "docstring": _ts_docstring(node, source, ext),
                "decorators": _parent_decs or [],
                "tags": [],
                "calls": [],
                "bases": _ts_bases(node, source),
                "faiss_id": -1,
            })
    # Variable assignment with arrow function: const foo = (x) => ...
    elif node.type in ("lexical_declaration", "variable_declaration"):
        for child in node.children:
            if child.type in ("variable_declarator",):
                vname = child.child_by_field_name("name")
                vval = child.child_by_field_name("value")
                if vname and vval and vval.type in ("arrow_function", "function_expression"):
                    calls: list[str] = []
                    _ts_collect_calls(vval, source, calls)
                    out.append({
                        "name": _ts_text(vname, source),
                        "type": "FUNCTION",
                        "start_line": node.start_point[0] + 1,
                        "end_line": node.end_point[0] + 1,
                        "docstring": "",
                        "decorators": [],
                        "tags": ["arrow"],
                        "calls": list(dict.fromkeys(calls)),
                        "bases": [],
                        "faiss_id": -1,
                    })
                    return  # don't recurse further — already captured
    for child in node.children:
        _walk_ts(child, source, ext, out)


def _extract_symbols_ts(tree, source: bytes, ext: str) -> list[dict]:
    """Extract symbols from a tree-sitter parse tree."""
    out: list[dict] = []
    _walk_ts(tree.root_node, source, ext, out)
    out.sort(key=lambda s: s["start_line"])
    return out


# ── import extraction (Python) ────────────────────────────────────────────────

def _extract_imports_py(tree: ast.AST) -> list[dict]:
    """Extract top-level import statements from a Python AST.

    Returns list of dicts: {module, alias, line, relative}.
    relative=True means it's a relative import (from . import X).
    """
    imports: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append({
                    "module": alias.name,
                    "alias": alias.asname or alias.name.split(".")[-1],
                    "line": node.lineno,
                    "relative": False,
                })
        elif isinstance(node, ast.ImportFrom):
            level_dots = "." * (node.level or 0)
            if node.module:
                imports.append({
                    "module": level_dots + node.module,
                    "alias": node.module.split(".")[-1],
                    "line": node.lineno,
                    "relative": (node.level or 0) > 0,
                })
            elif node.level:
                # bare relative: `from . import X, Y` — emit one entry per name
                for alias in node.names:
                    imports.append({
                        "module": level_dots + alias.name,
                        "alias": alias.asname or alias.name,
                        "line": node.lineno,
                        "relative": True,
                    })
    return imports


def _resolve_import_to_file(
    module: str,
    current_file: str,
    repo_root: str,
    tracked_files: "set[str] | None" = None,
) -> "str | None":
    """Attempt to resolve a Python import module name to a local file path.

    Returns a repo-relative path string, or None if not resolvable locally.
    """
    # Strip leading dots from relative imports
    module_clean = module.lstrip(".")
    if not module_clean:
        return None

    parts = module_clean.split(".")
    candidates = [
        os.path.join(*parts) + ".py",
        os.path.join(*parts, "__init__.py"),
    ]
    for candidate in candidates:
        abs_path = os.path.join(repo_root, candidate)
        if os.path.isfile(abs_path):
            if tracked_files is None or candidate in tracked_files:
                return candidate
    return None


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
            # Extract base class names for INHERITS edges
            bases: list[str] = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    bases.append(base.id)
                elif isinstance(base, ast.Attribute):
                    bases.append(base.attr)
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
                "bases": bases,
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

    # Deduplicate by (name, start_line): prefer LAMBDA > CONSTANT/VARIABLE
    # (the lambda block runs after the assignment block on the same node,
    # so the CONSTANT/VARIABLE entry is added first — we must overwrite it).
    dedup_map: dict[tuple, dict] = {}
    _TYPE_PRIO = {"LAMBDA": 2, "TYPED_FIELD": 1}
    for sym in symbols:
        key = (sym["name"], sym["start_line"])
        existing = dedup_map.get(key)
        if existing is None or _TYPE_PRIO.get(sym["type"], 0) > _TYPE_PRIO.get(existing["type"], 0):
            dedup_map[key] = sym
    deduped = list(dedup_map.values())

    deduped.sort(key=lambda s: s["start_line"])
    return deduped


# ── main indexer class ────────────────────────────────────────────────────────

def _find_entry_points(tracked: "set[str]") -> "list[str]":
    """Return likely entry-point files from the tracked set, ordered by priority.

    Supports Python, Go, Rust, JS/TS, Java, and Ruby conventions.
    For Go repos (Kubernetes-style): cmd/*/main.go are the canonical entry points.
    """
    found: list[str] = []
    seen: set[str] = set()

    def _add(f: str) -> None:
        if f not in seen:
            seen.add(f)
            found.append(f)

    # ── priority name matches (any depth) ─────────────────────────────────────
    _PRIORITY_NAMES = {
        # Python
        "__main__.py", "main.py", "app.py", "manage.py",
        "run.py", "server.py", "cli.py", "start.py", "wsgi.py", "asgi.py",
        # Go — prefer cmd/*/main.go pattern; also bare main.go
        "main.go",
        # Rust
        "main.rs",
        # JS / TS
        "index.js", "index.ts", "index.mjs", "server.js", "server.ts",
        "app.js", "app.ts", "main.js", "main.ts",
        # Java
        "Main.java", "Application.java", "App.java",
        # Ruby
        "main.rb", "app.rb", "config.ru",
    }
    for f in sorted(tracked):
        if Path(f).name in _PRIORITY_NAMES:
            _add(f)

    # ── Go: prefer cmd/*/main.go (Kubernetes / multi-binary pattern) ──────────
    cmd_mains = sorted(f for f in tracked if _re_tok.search(r"^cmd/[^/]+/main\.go$", f))
    for f in cmd_mains:
        _add(f)

    # ── Python fallback: top-level .py files ──────────────────────────────────
    if not found:
        for f in sorted(tracked):
            if "/" not in f and f.endswith(".py"):
                _add(f)

    # ── JS/TS fallback: package.json main/bin resolution ──────────────────────
    if not found:
        for f in sorted(tracked):
            if Path(f).name == "package.json":
                try:
                    import json as _json  # pylint: disable=import-outside-toplevel
                    data = _json.loads(Path(f).read_text(errors="ignore"))
                    main_rel = data.get("main") or data.get("bin")
                    if isinstance(main_rel, str) and main_rel in tracked:
                        _add(main_rel)
                except Exception:  # pylint: disable=broad-except
                    pass

    return found


def _expand_from_entry_points(
    entry_points: "list[str]",
    tracked: "set[str]",
    repo_root: str,
) -> "dict[str, float]":
    """BFS from entry points following Python imports within the tracked file set.

    Returns a dict mapping rel_path → index_weight:
      - 1.0  : entry points and files reachable within 1 hop
      - 0.75 : reachable at hop 2
      - 0.5  : reachable at hop 3+ (diminishing returns; still core dependency)

    Non-Python files in the tracked set are not BFS-reachable via imports;
    callers assign them a separate weight (typically 0.5).
    """
    import ast as _ast  # local to avoid polluting module namespace

    # Map: dotted-module-path → rel_file_path for all tracked .py files
    py_files = {f for f in tracked if f.endswith(".py")}
    module_map: "dict[str, str]" = {}
    for f in py_files:
        parts = Path(f).with_suffix("").parts
        module_map[".".join(parts)] = f
        if parts and parts[-1] == "__init__":
            module_map[".".join(parts[:-1])] = f

    def _resolve(module: str, current_file: str) -> "list[str]":
        candidates = []
        if module in module_map:
            candidates.append(module_map[module])
        for key, val in module_map.items():
            if key == module or key.startswith(module + "."):
                if val not in candidates:
                    candidates.append(val)
                break
        return candidates

    def _hop_weight(hop: int) -> float:
        if hop <= 1:
            return 1.0
        if hop == 2:
            return 0.75
        return 0.5

    # BFS with hop tracking — queue items are (rel_path, hop_depth)
    weights: "dict[str, float]" = {}
    for ep in entry_points:
        weights[ep] = 1.0
    from collections import deque as _deque  # pylint: disable=import-outside-toplevel
    queue: "_deque[tuple[str, int]]" = _deque([(ep, 0) for ep in entry_points])

    while queue:
        current, hop = queue.popleft()
        abs_path = os.path.join(repo_root, current)
        if not os.path.isfile(abs_path):
            continue
        try:
            source = Path(abs_path).read_bytes()
            tree = _ast.parse(source.decode("utf-8", errors="ignore"), filename=abs_path)
        except Exception:  # pylint: disable=broad-except
            continue

        next_hop = hop + 1
        next_weight = _hop_weight(next_hop)

        for node in _ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, _ast.Import):
                for alias in node.names:
                    targets.extend(_resolve(alias.name, current))
            elif isinstance(node, _ast.ImportFrom):
                mod = node.module or ""
                level = node.level or 0
                if level == 0 and mod:
                    targets.extend(_resolve(mod, current))
                elif level > 0:
                    # relative import: `from . import X` or `from .pkg import Y`
                    pkg_parts = Path(current).parent.parts
                    back = max(0, level - 1)
                    base_parts = pkg_parts[:len(pkg_parts) - back] if back < len(pkg_parts) else ()
                    if mod:
                        full = ".".join((*base_parts, mod))
                        targets.extend(_resolve(full, current))
                    else:
                        # bare `from . import X, Y` — resolve each name
                        for alias in node.names:
                            full = ".".join((*base_parts, alias.name))
                            targets.extend(_resolve(full, current))

            for target in targets:
                existing_w = weights.get(target, -1.0)
                if next_weight > existing_w:
                    weights[target] = next_weight
                    queue.append((target, next_hop))

    return weights


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

    def __init__(
        self,
        graph: KnowledgeGraph,
        *,
        progress_factory: Callable[[str, str, int], Any] | None = None,
    ) -> None:
        self.graph = graph
        # Interface-layer callback (interface.tools.bg_progress.TaskProgress) for
        # Tier-2 indexing progress, injected by callers to keep this module free
        # of upward `intelligence → interface` imports — see COGNIREPO-105.
        self._progress_factory = progress_factory
        self._model = None  # lazy: loaded only when embedding is actually performed
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

    # ── embedding model (lazy) ────────────────────────────────────────────────

    @property
    def model(self):
        if self._model is None:
            self._model = get_model()
        return self._model

    @model.setter
    def model(self, value):
        self._model = value

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
                ts_symbols = _extract_symbols_ts(tree, source, ext)
                if ext != ".py":
                    return ts_symbols
                # For Python: merge tree-sitter (FUNCTION/CLASS) with stdlib-ast
                # (CONSTANT/VARIABLE/TYPED_FIELD/LAMBDA) — each covers what the
                # other misses.
                try:
                    import warnings as _w  # pylint: disable=import-outside-toplevel
                    with _w.catch_warnings():
                        _w.simplefilter("ignore", SyntaxWarning)
                        tree_py = ast.parse(
                            source.decode("utf-8", errors="ignore"),
                            filename=abs_path,
                        )
                    py_symbols = _extract_symbols_py(tree_py, abs_path)
                except SyntaxError:
                    py_symbols = []
                # Keep tree-sitter FUNCTION/CLASS (richer call data);
                # add stdlib-ast symbols that tree-sitter never emits.
                ts_types = {"FUNCTION", "CLASS"}
                ts_names_lines: set[tuple] = {
                    (s["name"], s["start_line"]) for s in ts_symbols
                }
                extras = [
                    s for s in py_symbols
                    if s["type"] not in ts_types
                    and (s["name"], s["start_line"]) not in ts_names_lines
                ]
                return ts_symbols + extras
            except Exception as exc:  # pylint: disable=broad-except
                log.debug("tree-sitter parse failed for %s: %s", abs_path, exc)
                if ext != ".py":
                    return []
                # fall through to stdlib ast for Python

        if ext == ".py":
            try:
                import warnings as _w  # pylint: disable=import-outside-toplevel
                with _w.catch_warnings():
                    _w.simplefilter("ignore", SyntaxWarning)
                    tree_py = ast.parse(
                        source.decode("utf-8", errors="ignore"),
                        filename=abs_path,
                    )
                return _extract_symbols_py(tree_py, abs_path)
            except SyntaxError:
                return []

        return []

    # ── public API ────────────────────────────────────────────────────────────

    def _batch_embed_pending(self, batch_size: int = 256) -> None:
        """Encode all deferred embed texts in one batched model.encode() call.

        Collecting texts across all files and encoding them together is 20-50x
        faster than one encode() call per symbol because the transformer GPU/CPU
        kernel amortises overhead across the full batch.
        """
        pending = getattr(self, "_pending_embeds", [])
        if not pending:
            return
        texts = [p[0] for p in pending]
        print(f"  Embedding {len(texts):,} texts in batches of {batch_size}…")
        try:
            import numpy as _np  # pylint: disable=import-outside-toplevel
            from tqdm import tqdm  # pylint: disable=import-outside-toplevel
            _embed_gen = self.model.embed(texts)
            _vecs_list = list(tqdm(
                _embed_gen,
                total=len(texts),
                desc="Embedding",
                unit="vec",
                dynamic_ncols=True,
            ))
            vecs = _np.array(_vecs_list).astype("float32")
        except Exception as exc:  # pylint: disable=broad-except
            log.warning("Batch encode failed (%s) — skipping FAISS embed", exc)
            return
        for vec, (_, meta, sym) in zip(vecs, pending):
            faiss_id = len(self.faiss_meta)
            self.faiss_index.add_with_ids(
                np.array([vec], dtype="float32"),
                np.array([faiss_id], dtype=np.int64),
            )
            self.faiss_meta.append(meta)
            if sym is not None:
                sym["faiss_id"] = faiss_id
        self._pending_embeds.clear()

    def index_repo(
        self,
        repo_root: str,
        embed: bool = True,
        skip_graph: bool | None = None,
        tier: "int | str | None" = None,
    ) -> dict:
        """
        Walk *repo_root*, index every supported file (skipping _SKIP_DIRS),
        build the reverse index, and save everything to disk.
        Returns a summary dict with per-language file counts.

        Parameters
        ----------
        embed : If False, skip FAISS embedding (AST/symbol index + graph only).
                Faster for CI or when only symbol lookup is needed.
        skip_graph : If True, skip knowledge-graph node/edge building entirely.
                     Defaults to auto (True when source files > _AUTO_SKIP_GRAPH_THRESHOLD).
                     Prevents OOM on very large repos (e.g. kubernetes at 23k files → 2.9 GB).
        tier : Tiered indexing for large repos (>_LARGE_REPO_TIER_THRESHOLD files):
               None  → auto: Tier 1 for large repos, full index for small repos.
               1     → Tier 1 only: index w≥0.75 files (fast, ~5 min for large repos).
               2     → Tier 2 only: index w<0.75 files from pending_tier2.json queue.
               "all" → index everything regardless of size (current small-repo behaviour).
        """
        self._embed_enabled = embed  # pylint: disable=attribute-defined-outside-init
        # Batch mode: defer all model.encode() calls; flush once at the end
        # for a 20-50x speedup on large repos.
        self._batch_mode = embed  # pylint: disable=attribute-defined-outside-init
        self._pending_embeds: list = []  # pylint: disable=attribute-defined-outside-init
        self._skip_graph: bool = False  # pylint: disable=attribute-defined-outside-init
        self._graph_weight_min: float = 0.0  # pylint: disable=attribute-defined-outside-init
        self._ensure_faiss()
        repo_root = os.path.abspath(repo_root)
        self.index_data["repo_root"] = repo_root
        self.index_data["indexed_at"] = _now()

        skip_dirs = _effective_skip_dirs()

        # ── git-first + entry-point file discovery ──────────────────────────────
        _git_root = os.path.join(repo_root, ".git")
        _tracked: "set[str] | None" = None
        # file_weights: rel_path → index weight (1.0 direct, 0.75 hop-2, 0.5 indirect)
        _file_weights: "dict[str, float]" = {}
        if os.path.exists(_git_root):
            _tracked = _git_tracked_files(repo_root)
            if _tracked is not None:
                _entries = _find_entry_points(_tracked)
                if _entries:
                    _bfs_weights = _expand_from_entry_points(_entries, _tracked, repo_root)
                    _non_py = {f for f in _tracked if not f.endswith(".py")}
                    # Non-Python files: git-tracked but not import-reachable → weight 0.5
                    _file_weights = {**{f: 0.5 for f in _non_py}, **_bfs_weights}
                    # Git-tracked Python files NOT reached by BFS → weight 0.5
                    for f in _tracked:
                        if f not in _file_weights:
                            _file_weights[f] = 0.5
                    _tracked = set(_file_weights.keys())
                    _direct = sum(1 for w in _bfs_weights.values() if w >= 1.0)
                    print(
                        f"  Git repo + weighted crawl: {len(_tracked)} file(s) — "
                        f"{_direct} direct (w=1.0), "
                        f"{len(_tracked) - _direct} indirect (w≤0.75) "
                        f"from {len(_entries)} entry point(s) "
                        f"({', '.join(Path(e).name for e in _entries[:3])}"
                        f"{'...' if len(_entries) > 3 else ''})"
                    )
                else:
                    _file_weights = {f: 0.5 for f in _tracked}
                    print(f"  Git repo detected — indexing {len(_tracked)} tracked file(s) (no entry points, all w=0.5).")

        # ── large-repo warning (embed pass only) ────────────────────────────────
        if _tracked is not None:
            _n_candidates = sum(1 for f in _tracked if is_supported(Path(f)))
        else:
            _n_candidates = 0
            for _dp, _dns, _fns in os.walk(repo_root):
                _dns[:] = [d for d in _dns if d not in skip_dirs]
                _n_candidates += sum(1 for f in _fns if is_supported(Path(f)))

        if embed and _n_candidates > _LARGE_REPO_FILE_THRESHOLD:
            print(
                f"  ⚠  Large repo detected ({_n_candidates} source files). "
                "First-run tip: use --no-embed for a faster symbol-only index, "
                "then run index-repo again to add embeddings."
            )

        # Graph mode selection for large repos.
        # skip_graph=True  → no graph at all (--no-graph flag).
        # skip_graph=None  → auto: lite-graph (w≥0.75 only) for large repos, full graph for small.
        # skip_graph=False → force full graph regardless of size (risks OOM).
        if skip_graph is True:
            self._skip_graph = True  # pylint: disable=attribute-defined-outside-init
            self._graph_weight_min = 1.1  # effectively blocks all nodes  # pylint: disable=attribute-defined-outside-init
        elif skip_graph is False:
            self._skip_graph = False  # pylint: disable=attribute-defined-outside-init
            self._graph_weight_min = 0.0  # pylint: disable=attribute-defined-outside-init
        else:
            # Auto mode: lite-graph for large repos
            if _n_candidates > _AUTO_SKIP_GRAPH_THRESHOLD:
                self._skip_graph = False  # pylint: disable=attribute-defined-outside-init
                self._graph_weight_min = _LITE_GRAPH_WEIGHT_MIN  # pylint: disable=attribute-defined-outside-init
                print(
                    f"  ℹ  Large repo ({_n_candidates} files): lightweight graph mode — "
                    f"only symbols with weight≥{_LITE_GRAPH_WEIGHT_MIN} (direct + hop-2 reachable). "
                    "Use --no-graph to disable entirely, or skip_graph=False to force full graph."
                )
            else:
                self._skip_graph = False  # pylint: disable=attribute-defined-outside-init
                self._graph_weight_min = 0.0  # pylint: disable=attribute-defined-outside-init

        lang_file_counts: dict[str, int] = defaultdict(int)
        skipped_exts: set[str] = set()
        total_files = 0

        _skip_noise = {
            ".md", ".txt", ".json", ".toml",
            ".cfg", ".ini", ".lock", ".gitignore", ".env",
            ".png", ".jpg", ".gif", ".svg", ".ico",
            ".whl", ".zip", ".tar", ".gz",
        }

        # ── Tiered indexing: resolve effective tier ───────────────────────────
        # tier=None → auto: Tier 1 for large repos (≥threshold), full for small.
        # tier=1    → Tier 1 only (w≥0.5, all BFS-reachable). Queues truly unvisited files.
        # tier=2    → Tier 2 only: reads pending_tier2.json, processes unvisited files.
        # tier="all"→ full index regardless of size.
        _is_large_repo = _n_candidates >= _LARGE_REPO_TIER_THRESHOLD
        if tier is None:
            _effective_tier: "int | str" = 1 if _is_large_repo else "all"
        else:
            _effective_tier = tier

        # Tier 2: read the pending queue instead of walking the repo
        if _effective_tier == 2:
            return self._index_tier2(repo_root, embed)

        from tqdm import tqdm  # pylint: disable=import-outside-toplevel

        # For large repos in auto Tier 1: skip embedding (30-min bottleneck for 150k+ vectors).
        # AST symbol lookup works immediately. Tier 2 background pass handles embeddings.
        _embed_deferred = False
        _effective_embed = embed
        if _is_large_repo and _effective_tier == 1 and embed:
            _effective_embed = False
            _embed_deferred = True
            print(
                "  ℹ  Large repo: FAISS embedding deferred to Tier 2 background. "
                "Symbol lookup (AST index) works immediately. "
                "Run 'cognirepo index-repo . --tier 2' to add semantic embeddings."
            )
        self._embed_enabled = _effective_embed  # pylint: disable=attribute-defined-outside-init

        # Build the file list: apply tier filter if Tier 1
        _tier2_pending: list[dict] = []  # files deferred for background Tier 2

        if _tracked is not None:
            _sorted_tracked = sorted(_tracked)
            _pbar = tqdm(_sorted_tracked, desc="Indexing files", unit="file", dynamic_ncols=True)
            for rel_path in _pbar:
                abs_path = os.path.join(repo_root, rel_path)
                if not os.path.isfile(abs_path):
                    continue
                ext = Path(rel_path).suffix
                if not is_supported(Path(rel_path)):
                    if ext and ext not in _skip_noise:
                        skipped_exts.add(ext)
                    continue
                _w = _file_weights.get(rel_path, 0.5)
                # Tier 1: defer low-weight files to pending_tier2 queue
                if _effective_tier == 1 and _w < _TIER1_WEIGHT_MIN:
                    _tier2_pending.append({"rel_path": rel_path, "abs_path": abs_path, "weight": _w})
                    continue
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", SyntaxWarning)
                        self.index_file(rel_path, abs_path, weight=_w)
                    lang_file_counts[lang_label(ext)] += 1
                    total_files += 1
                    _pbar.set_postfix({"file": Path(rel_path).name[:30]}, refresh=False)
                except Exception as exc:  # pylint: disable=broad-except
                    log.debug("  [skip] %s: %s", rel_path, exc)
        else:
            _all_files: list[tuple[str, str]] = []
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
                    _all_files.append((rel_path, abs_path))
            _pbar = tqdm(_all_files, desc="Indexing files", unit="file", dynamic_ncols=True)
            for rel_path, abs_path in _pbar:
                ext = Path(rel_path).suffix
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", SyntaxWarning)
                        self.index_file(rel_path, abs_path, weight=1.0)
                    lang_file_counts[lang_label(ext)] += 1
                    total_files += 1
                    _pbar.set_postfix({"file": Path(rel_path).name[:30]}, refresh=False)
                except Exception as exc:  # pylint: disable=broad-except
                    log.debug("  [skip] %s: %s", rel_path, exc)

        # Write pending_tier2.json if Tier 1 deferred any files, or if embeddings deferred
        if _tier2_pending or _embed_deferred:
            self._write_pending_tier2(repo_root, _tier2_pending, embed_pending=_embed_deferred)

        # ── flush deferred batch embeddings ──────────────────────────────────
        if _effective_embed:
            self._batch_embed_pending()
        self._batch_mode = False  # pylint: disable=attribute-defined-outside-init

        self._build_reverse_index()
        # Resolve symbol:: stub nodes to real file-qualified nodes where unambiguous.
        if not getattr(self, "_skip_graph", False):
            self._resolve_call_stubs()
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

        if _tier2_pending:
            print(
                f"  ℹ  Tier 1 complete ({total_files} files, {total_symbols} symbols). "
                f"Tier 2: {len(_tier2_pending)} low-weight files queued for background indexing. "
                "Run: cognirepo index-repo . --tier 2"
            )

        # NOTE: doc ingestion deliberately does NOT run here. Every entry point
        # (cli/main.py index-repo Stage 3, cli/init_project.py, init-all) invokes
        # DocIngester itself, AFTER free_large_objects(). Running it inside
        # index_repo ingested every chunk TWICE (duplicate doc hits in
        # search_docs) and executed at peak RSS — observed as a native
        # segfault at the end of a large-repo tier-2 run.

        return {
            "files": total_files,
            "symbols": total_symbols,
            "languages": dict(lang_file_counts),
            "skipped_extensions": sorted(skipped_exts),
            "tier2_queued": len(_tier2_pending),
        }

    def index_file(self, rel_path: str, abs_path: str | None = None, weight: float = 1.0) -> dict:
        """
        Index one file. Skips if sha256 matches existing entry or file > max_file_bytes.

        weight: crawl weight assigned by index_repo (1.0 = directly reachable from
                entry points, 0.75 = hop-2, 0.5 = git-tracked but not import-reachable).
                Stored in each symbol record, FAISS meta, and graph node so retrieval
                can boost core symbols over peripheral ones.

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

        # remove stale graph nodes so deleted/renamed symbols don't linger
        if existing:
            self.graph.remove_file_nodes(rel_path)

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

        # embed + add to FAISS (skipped when embed=False / --no-embed / config/data ext)
        embed_enabled = getattr(self, "_embed_enabled", True) and ext not in _NO_EMBED_EXTS

        # Pre-read source lines once per file for body-snippet enrichment
        _src_lines: list[str] = []
        if embed_enabled:
            try:
                with open(abs_path, encoding="utf-8", errors="replace") as _sf:
                    _src_lines = _sf.readlines()
            except OSError:
                pass

        for sym in raw_symbols:
            sym["weight"] = weight  # crawl weight for retrieval scoring
            sym["faiss_id"] = -1   # filled by _batch_embed_pending() or inline below

            if embed_enabled:
                # Enriched embed text: type + name + decorators + docstring +
                # first 3 body lines (signature context) + top callees
                dec_str = " ".join(sym.get("decorators", []))
                calls_str = ", ".join(sym.get("calls", [])[:3])
                body_snippet = ""
                if _src_lines:
                    start = sym.get("start_line", 1)
                    end = min(start + 3, sym.get("end_line", start + 3))
                    snippet_lines = _src_lines[start - 1 : end]
                    body_snippet = " ".join(l.strip() for l in snippet_lines if l.strip())[:200]
                embed_text = " ".join(filter(None, [
                    sym["type"], sym["name"], dec_str,
                    sym.get("docstring", ""), body_snippet,
                    f"calls: {calls_str}" if calls_str else "",
                ]))
                meta = {
                    "name": sym["name"], "type": sym["type"],
                    "file": rel_path, "start_line": sym["start_line"],
                    "docstring": sym.get("docstring", ""),
                    "decorators": sym.get("decorators", []),
                    "source": "symbol", "weight": weight,
                }
                if getattr(self, "_batch_mode", False):
                    # Defer encoding — accumulate for batch encode in index_repo
                    self._pending_embeds.append((embed_text, meta, sym))  # type: ignore[attr-defined]
                else:
                    vec = next(iter(self.model.embed([embed_text]))).astype("float32")
                    faiss_id = len(self.faiss_meta)
                    self.faiss_index.add_with_ids(
                        np.array([vec], dtype="float32"),
                        np.array([faiss_id], dtype=np.int64),
                    )
                    self.faiss_meta.append(meta)
                    sym["faiss_id"] = faiss_id

            # knowledge graph — skipped or weight-filtered for large repos to prevent OOM
            _graph_min = getattr(self, "_graph_weight_min", 0.0)
            if not getattr(self, "_skip_graph", False) and weight >= _graph_min:
                file_node = make_node_id("FILE", rel_path)
                sym_node = node_id_from_symbol_record(sym, rel_path)
                self.graph.add_node(file_node, NodeType.FILE, weight=weight)
                self.graph.add_node(sym_node, sym["type"], file=rel_path, line=sym["start_line"], weight=weight)
                self.graph.add_edge(sym_node, file_node, EdgeType.DEFINED_IN)

        # ── file-level summary embedding ──────────────────────────────────────
        if embed_enabled and raw_symbols:
            fn_names = [s["name"] for s in raw_symbols if s["type"] == "FUNCTION"][:8]
            cls_names = [s["name"] for s in raw_symbols if s["type"] == "CLASS"][:4]
            _first_doc = next(
                (s.get("docstring", "") for s in raw_symbols
                 if s.get("docstring") and s["type"] in ("FUNCTION", "CLASS")),
                "",
            )
            file_embed_text = " ".join(filter(None, [
                "FILE", os.path.basename(rel_path),
                os.path.splitext(os.path.basename(rel_path))[0].replace("_", " "),
                _first_doc[:120] if _first_doc else "",
                f"functions: {', '.join(fn_names)}" if fn_names else "",
                f"classes: {', '.join(cls_names)}" if cls_names else "",
            ]))
            file_meta = {
                "name": os.path.basename(rel_path), "type": "FILE",
                "file": rel_path, "start_line": 1,
                "docstring": _first_doc[:120],
                "source": "file_summary", "weight": weight,
            }
            if getattr(self, "_batch_mode", False):
                self._pending_embeds.append((file_embed_text, file_meta, None))  # type: ignore[attr-defined]
            else:
                try:
                    _fvec = next(iter(self.model.embed([file_embed_text]))).astype("float32")
                    _fid = len(self.faiss_meta)
                    self.faiss_index.add_with_ids(
                        np.array([_fvec], dtype="float32"),
                        np.array([_fid], dtype=np.int64),
                    )
                    self.faiss_meta.append(file_meta)
                except Exception:  # pylint: disable=broad-except
                    pass

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

        # inheritance edges — CLASS → base class
        for sym in raw_symbols:
            if sym["type"] == "CLASS":
                sym_node = node_id_from_symbol_record(sym, rel_path)
                for base_name in sym.get("bases", []):
                    if base_name in ("object", "ABC", "Enum", "IntEnum"):
                        continue  # skip stdlib noise
                    base_node = f"symbol::{base_name}"
                    self.graph.add_node(base_node, NodeType.CONCEPT)
                    self.graph.add_edge(sym_node, base_node, EdgeType.INHERITS)

        # import edges — current file → imported local file
        if ext == ".py":
            try:
                _src_bytes = Path(abs_path).read_bytes()
                _tree_for_imports = ast.parse(
                    _src_bytes.decode("utf-8", errors="ignore"), filename=abs_path
                )
                _imports = _extract_imports_py(_tree_for_imports)
                _repo_root = self.index_data.get("repo_root") or os.getcwd()
                file_node = make_node_id("FILE", rel_path)
                for imp in _imports:
                    _target = _resolve_import_to_file(
                        imp["module"], rel_path, _repo_root
                    )
                    if _target:
                        target_node = make_node_id("FILE", _target)
                        self.graph.add_node(target_node, NodeType.FILE)
                        self.graph.add_edge(file_node, target_node, EdgeType.IMPORTS)
            except (SyntaxError, OSError):
                pass  # best-effort

        file_record = {
            "indexed_at": _now(),
            "sha256": sha,
            "language": lang_label(ext),
            "weight": weight,
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

    def _resolve_call_stubs(self, names: set[str] | None = None) -> None:
        """
        Second-pass stub resolution: for each ``symbol::fn`` node, look up fn in
        the complete reverse_index.  When exactly one definition exists, redirect
        all call edges to the real ``file::fn`` node and remove the stub.  When
        multiple definitions exist (ambiguous), keep the stub and tag it
        ``ambiguous=True``.  Unresolved stubs (no definition found) are tagged
        ``unresolved=True`` so ``who_calls`` can still surface them.

        names: when given, only reconcile ``symbol::{n}`` for ``n in names``
        instead of scanning every stub node in the graph — used by the
        watcher's incremental ``flush()`` to keep per-save cost proportional
        to the batch size rather than the whole graph (COGNIREPO-D10). The
        full-reindex path (`index_repo()`) keeps calling this with no
        argument to sweep everything.

        Must be called AFTER ``_build_reverse_index()`` so the index is complete.
        Skipped when the graph is empty (graph indexing was disabled).
        """
        from data.graph.knowledge_graph import EdgeType, NodeType  # pylint: disable=import-outside-toplevel

        if self.graph.G.number_of_nodes() == 0:
            return

        rev = self.index_data.get("reverse_index", {})
        if names is not None:
            stub_nodes = [
                f"symbol::{n}" for n in names if self.graph.G.has_node(f"symbol::{n}")
            ]
        else:
            stub_nodes = [n for n in list(self.graph.G.nodes()) if n.startswith("symbol::")]

        for stub in stub_nodes:
            fn_name = stub[len("symbol::"):]
            locations = rev.get(fn_name, [])

            if len(locations) == 1:
                # Unambiguous — redirect edges to the real node
                file_path, line = locations[0][0], locations[0][1]
                real_node = f"{file_path}::{fn_name}"
                if not self.graph.G.has_node(real_node):
                    self.graph.add_node(real_node, NodeType.FUNCTION,
                                        file=file_path, line=line)
                # Redirect outgoing edges (CALLS → callers)
                for successor in list(self.graph.G.successors(stub)):
                    edge_data = dict(self.graph.G[stub][successor])
                    if not self.graph.G.has_edge(real_node, successor):
                        self.graph.G.add_edge(real_node, successor, **edge_data)
                # Redirect incoming edges (CALLED_BY from callers)
                for predecessor in list(self.graph.G.predecessors(stub)):
                    edge_data = dict(self.graph.G[predecessor][stub])
                    if not self.graph.G.has_edge(predecessor, real_node):
                        self.graph.G.add_edge(predecessor, real_node, **edge_data)
                self.graph.G.remove_node(stub)

            elif len(locations) > 1:
                self.graph.G.nodes[stub]["ambiguous"] = True
                self.graph.G.nodes[stub]["candidates"] = [loc[0] for loc in locations]

            else:
                self.graph.G.nodes[stub]["unresolved"] = True

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

    # ── tiered indexing helpers ───────────────────────────────────────────────

    def _write_pending_tier2(
        self, repo_root: str, pending: "list[dict]", embed_pending: bool = False
    ) -> None:
        """Write the Tier 2 pending queue to disk (thread-safe via filelock)."""
        import json as _json  # pylint: disable=import-outside-toplevel
        from core.config.paths import pending_tier2_path  # pylint: disable=import-outside-toplevel
        try:
            import filelock as _fl  # pylint: disable=import-outside-toplevel
            _lock = _fl.FileLock(pending_tier2_path() + ".lock", timeout=10)
            with _lock:
                with open(pending_tier2_path(), "w", encoding="utf-8") as _f:
                    _json.dump(
                        {
                            "repo_root": repo_root,
                            "files": pending,
                            "embed_pending": embed_pending,
                            "total_queued": len(pending),
                        },
                        _f, indent=2,
                    )
        except Exception as _exc:  # pylint: disable=broad-except
            log.warning("Could not write pending_tier2.json: %s", _exc)

    def _repopulate_embeds_from_index(self) -> None:
        """
        Rebuild _pending_embeds from the existing in-memory AST index.
        Called by Tier 2 when embedding was deferred in Tier 1 (large repos).
        """
        self._pending_embeds = []  # pylint: disable=attribute-defined-outside-init
        for rel_path, file_data in self.index_data.get("files", {}).items():
            for sym in file_data.get("symbols", []):
                name = sym.get("name", "")
                doc = sym.get("docstring", "")
                embed_text = f"{name} {doc}".strip() if doc else name
                meta = {
                    "file": rel_path, "name": name, "line": sym.get("start_line", 0),
                    "type": sym.get("type", ""), "source": "symbol",
                }
                self._pending_embeds.append((embed_text, meta, sym))
            # File-level embed
            file_embed_text = f"file {rel_path}"
            file_meta = {"file": rel_path, "name": rel_path, "line": 0, "type": "FILE", "source": "file"}
            self._pending_embeds.append((file_embed_text, file_meta, None))

    def _index_tier2(self, repo_root: str, embed: bool) -> dict:
        """
        Process the Tier 2 pending queue (low-weight files not indexed in Tier 1).
        Reads pending_tier2.json, indexes in batches of 500, updates progress file.
        """
        # Load existing Tier 1 AST index first — without this, self.save() at the end
        # would overwrite the Tier 1 data with an empty dict (fresh subprocess has no index).
        self.load()

        import json as _json  # pylint: disable=import-outside-toplevel
        from core.config.paths import pending_tier2_path, tier2_progress_path  # pylint: disable=import-outside-toplevel
        from tqdm import tqdm  # pylint: disable=import-outside-toplevel

        _queue_path = pending_tier2_path()
        if not os.path.exists(_queue_path):
            print("  Tier 2: no pending queue found. Run Tier 1 first: cognirepo index-repo . --tier 1")
            return {"files": 0, "symbols": 0, "languages": {}, "skipped_extensions": [], "tier2_queued": 0}

        try:
            import filelock as _fl  # pylint: disable=import-outside-toplevel
            _lock = _fl.FileLock(_queue_path + ".lock", timeout=30)
            with _lock:
                with open(_queue_path, encoding="utf-8") as _f:
                    _data = _json.load(_f)
        except Exception as _exc:  # pylint: disable=broad-except
            log.error("Tier 2: failed to read pending queue: %s", _exc)
            return {"files": 0, "symbols": 0, "languages": {}, "skipped_extensions": [], "tier2_queued": 0}

        _pending: list[dict] = _data.get("files", [])
        _embed_pending: bool = _data.get("embed_pending", False)
        _batch_size = 500
        lang_file_counts: dict[str, int] = defaultdict(int)
        total_files = 0
        skipped_exts: set[str] = set()
        _remaining = list(_pending)

        # If embedding was deferred in Tier 1 (large repo), embed all already-indexed files first.
        if _embed_pending and embed:
            print("  Tier 2: running deferred FAISS embedding for already-indexed files…")
            self._repopulate_embeds_from_index()
            self._batch_embed_pending()
            _data["embed_pending"] = False
            try:
                import filelock as _fl  # pylint: disable=import-outside-toplevel
                with _fl.FileLock(_queue_path + ".lock", timeout=10):
                    with open(_queue_path, "w", encoding="utf-8") as _qf:
                        import json as _j2  # pylint: disable=import-outside-toplevel
                        _j2.dump(_data, _qf, indent=2)
            except Exception:  # pylint: disable=broad-except
                pass

        print(f"  Tier 2: processing {len(_pending)} queued files in batches of {_batch_size}…")
        _pbar = tqdm(_pending, desc="Tier 2 indexing", unit="file", dynamic_ncols=True)

        # edge: set up progress tracker — failure falls back to tqdm-only silently
        _t2_prog = None
        try:
            if self._progress_factory is not None:
                import time as _t2time  # pylint: disable=import-outside-toplevel
                _t2_prog = self._progress_factory(
                    f"tier2_index_{int(_t2time.time())}", "Tier 2 indexing", len(_pending)
                )
        except Exception:  # pylint: disable=broad-except
            pass

        for _idx_t2, _entry in enumerate(_pbar):
            rel_path = _entry["rel_path"]
            abs_path = _entry["abs_path"]
            _w = _entry.get("weight", 0.5)
            ext = Path(rel_path).suffix
            if not os.path.isfile(abs_path):
                _remaining = [e for e in _remaining if e["rel_path"] != rel_path]
                continue
            # edge: stop check — failure is ignored, loop continues
            try:
                if _t2_prog is not None and _t2_prog.should_stop():
                    log.info("Tier 2 indexing stopped by user request.")
                    break
            except Exception:  # pylint: disable=broad-except
                pass

            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", SyntaxWarning)
                    self.index_file(rel_path, abs_path, weight=_w)
                lang_file_counts[lang_label(ext)] += 1
                total_files += 1
                _pbar.set_postfix({"file": Path(rel_path).name[:30]}, refresh=False)
            except Exception as _exc:  # pylint: disable=broad-except
                log.debug("  [tier2-skip] %s: %s", rel_path, _exc)
            finally:
                _remaining = [e for e in _remaining if e["rel_path"] != rel_path]

            # edge: update progress tracker — failure never interrupts indexing
            try:
                if _t2_prog is not None:
                    _t2_prog.update(_idx_t2 + 1, Path(rel_path).name[:30])
            except Exception:  # pylint: disable=broad-except
                pass

            # Flush batch and write progress every _batch_size files
            if total_files % _batch_size == 0:
                if embed:
                    self._batch_embed_pending()
                self._build_reverse_index()
                self.save()
                try:
                    import json as _j  # pylint: disable=import-outside-toplevel
                    with _fl.FileLock(_queue_path + ".lock", timeout=10):
                        with open(_queue_path, "w", encoding="utf-8") as _qf:
                            _j.dump({"repo_root": repo_root, "files": _remaining, "embed_pending": False}, _qf, indent=2)
                    with open(tier2_progress_path(), "w", encoding="utf-8") as _pf:
                        _j.dump({"processed": total_files, "remaining": len(_remaining)}, _pf, indent=2)
                except Exception:  # pylint: disable=broad-except
                    pass

        if embed:
            self._batch_embed_pending()
        self._batch_mode = False  # pylint: disable=attribute-defined-outside-init
        self._build_reverse_index()
        total_symbols = sum(len(f.get("symbols", [])) for f in self.index_data["files"].values())
        self.index_data["total_symbols"] = total_symbols
        self.save()

        # Clear the queue when done
        try:
            os.remove(_queue_path)
            _prog = tier2_progress_path()
            if os.path.exists(_prog):
                os.remove(_prog)
        except OSError:
            pass

        # edge: mark progress complete — failure is irrelevant, task is done
        try:
            if _t2_prog is not None:
                _t2_prog.complete()
        except Exception:  # pylint: disable=broad-except
            pass

        print(f"  Tier 2 complete: {total_files} additional files indexed.")
        return {
            "files": total_files, "symbols": total_symbols,
            "languages": dict(lang_file_counts),
            "skipped_extensions": sorted(skipped_exts), "tier2_queued": 0,
        }

    # ── lookup ────────────────────────────────────────────────────────────────

    @functools.lru_cache(maxsize=512)
    def lookup_symbol(self, symbol_name: str) -> list[dict]:
        """O(1) reverse-index lookup. Returns [{'file': str, 'line': int}]."""
        entries = self.index_data.get("reverse_index", {}).get(symbol_name, [])
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

    def free_large_objects(self) -> None:
        """Free FAISS index, AST symbol dicts, and pending embeds from RAM.

        Call after save() completes and before kg.save() to reduce RSS peak
        on large repos. Frees ~400–700 MB that would otherwise cause the
        circuit breaker to fire during graph serialization.
        """
        import gc  # pylint: disable=import-outside-toplevel
        self.faiss_index = None
        self.faiss_meta = []
        self.index_data = {
            "files": {}, "reverse_index": {},
            "repo_root": self.index_data.get("repo_root", ""),
            "indexed_at": self.index_data.get("indexed_at", ""),
        }
        self._pending_embeds = []  # pylint: disable=attribute-defined-outside-init
        gc.collect()

    # ── persistence ───────────────────────────────────────────────────────────

    @staticmethod
    def _atomic_json_dump(obj, path: str) -> None:
        """Write JSON to a tmp file then os.replace() into place.

        A crash or concurrent reindex mid-write can no longer leave a
        truncated/corrupt JSON file behind (observed as a parse error at
        char 73M on a large-monorepo ast_index.json).
        """
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)

    @staticmethod
    def _load_json_self_heal(path: str, default):
        """Load JSON; on corruption rename the file to .corrupt and return default."""
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            log.warning(
                "%s is corrupt or unreadable (%s). Renaming to .corrupt and "
                "starting fresh — re-run `cognirepo index-repo .` to rebuild.",
                os.path.basename(path), exc,
            )
            try:
                os.replace(path, path + ".corrupt")
            except OSError:
                pass
            return default

    def save(self) -> None:
        """Persist AST index, FAISS index, and metadata to disk.
        Also writes manifest.json with git SHA, platform info, and checksums
        so `cognirepo verify-index` can detect staleness or corruption later.
        """
        os.makedirs(os.path.dirname(_ast_index_file()), exist_ok=True)
        self._atomic_json_dump(self.index_data, _ast_index_file())
        if self.faiss_index is not None:
            faiss.write_index(self.faiss_index, _ast_faiss_file())
        self._atomic_json_dump(self.faiss_meta, _ast_meta_file())

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
            loaded = self._load_json_self_heal(_ast_index_file(), None)
            if loaded is not None:
                self.index_data = loaded
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
            self.faiss_meta = self._load_json_self_heal(_ast_meta_file(), [])
        self._loaded = True
