# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

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
import hashlib
import json
import logging
import os
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

AST_INDEX_FILE = ".cognirepo/index/ast_index.json"
AST_FAISS_FILE = ".cognirepo/index/ast.index"
AST_META_FILE  = ".cognirepo/index/ast_metadata.json"

_SKIP_DIRS = {
    ".git", "venv", "__pycache__", ".cognirepo", "node_modules",
    ".mypy_cache", ".venv", "dist", "build", "target", ".eggs",
}

# tree-sitter node types that represent named functions / methods
_TS_FUNCTION_TYPES = frozenset({
    "function_definition",   # Python, C++
    "function_declaration",  # JS, Java, Go, C
    "function_item",         # Rust
    "method_declaration",    # Java, C#
    "method_definition",     # JS class methods
    "function_expression",   # JS assigned function
})

# tree-sitter node types that represent named classes / types
_TS_CLASS_TYPES = frozenset({
    "class_definition",      # Python
    "class_declaration",     # Java, JS
    "class_specifier",       # C++
    "struct_item",           # Rust
    "interface_declaration", # Java, TS
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

def _extract_symbols_py(tree: ast.AST, file_path: str) -> list[dict]:
    """
    Walk a Python stdlib AST and collect FunctionDef, AsyncFunctionDef,
    ClassDef nodes.  Used when tree-sitter-python is not installed.
    """
    symbols: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sym_type = "FUNCTION"
        elif isinstance(node, ast.ClassDef):
            sym_type = "CLASS"
        else:
            continue

        docstring = ast.get_docstring(node) or ""
        end_line = getattr(node, "end_lineno", node.lineno)

        calls: list[str] = []
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func = child.func
                if isinstance(func, ast.Name):
                    calls.append(func.id)
                elif isinstance(func, ast.Attribute):
                    calls.append(func.attr)

        symbols.append({
            "name": node.name,
            "type": sym_type,
            "start_line": node.lineno,
            "end_line": end_line,
            "docstring": docstring[:300],
            "calls": list(dict.fromkeys(calls)),
            "faiss_id": -1,
        })

    symbols.sort(key=lambda s: s["start_line"])
    return symbols


# ── main indexer class ────────────────────────────────────────────────────────

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
            "faiss_index_file": AST_FAISS_FILE,
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

    def index_repo(self, repo_root: str) -> dict:
        """
        Walk *repo_root*, index every supported file (skipping _SKIP_DIRS),
        build the reverse index, and save everything to disk.
        Returns a summary dict with per-language file counts.
        """
        self._ensure_faiss()
        repo_root = os.path.abspath(repo_root)
        self.index_data["repo_root"] = repo_root
        self.index_data["indexed_at"] = _now()

        lang_file_counts: dict[str, int] = defaultdict(int)
        skipped_exts: set[str] = set()
        total_files = 0

        for dirpath, dirnames, filenames in os.walk(repo_root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in filenames:
                ext = Path(fname).suffix
                if not is_supported(Path(fname)):
                    # Track extensions we know exist but have no grammar for
                    if ext and ext not in {
                        ".md", ".txt", ".json", ".yaml", ".yml", ".toml",
                        ".cfg", ".ini", ".lock", ".gitignore", ".env",
                        ".png", ".jpg", ".gif", ".svg", ".ico",
                        ".whl", ".zip", ".tar", ".gz",
                    }:
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

        return {
            "files": total_files,
            "symbols": total_symbols,
            "languages": dict(lang_file_counts),
            "skipped_extensions": sorted(skipped_exts),
        }

    def index_file(self, rel_path: str, abs_path: str | None = None) -> dict:
        """
        Index one file. Skips if sha256 matches existing entry.
        Returns the file record dict.
        """
        ext = Path(rel_path).suffix
        if not is_supported(Path(rel_path)):
            return {}

        self._ensure_faiss()
        if abs_path is None:
            abs_path = rel_path

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

        # embed + add to FAISS
        for sym in raw_symbols:
            embed_text = f"{sym['type']} {sym['name']}: {sym.get('docstring', '')}"
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
            })
            sym["faiss_id"] = faiss_id

            # knowledge graph
            file_node = make_node_id("FILE", rel_path)
            sym_node = node_id_from_symbol_record(sym, rel_path)
            self.graph.add_node(file_node, NodeType.FILE)
            self.graph.add_node(sym_node, sym["type"], file=rel_path, line=sym["start_line"])
            self.graph.add_edge(sym_node, file_node, EdgeType.DEFINED_IN)

        # call-graph edges
        for sym in raw_symbols:
            caller_node = node_id_from_symbol_record(sym, rel_path)
            for callee_name in sym.get("calls", []):
                callee_node = f"symbol::{callee_name}"
                self.graph.add_node(callee_node, NodeType.CONCEPT)
                self.graph.add_edge(caller_node, callee_node, EdgeType.CALLED_BY)

        file_record = {
            "indexed_at": _now(),
            "sha256": sha,
            "language": lang_label(ext),
            "symbols": raw_symbols,
        }
        self.index_data["files"][rel_path] = file_record
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

    # ── lookup ────────────────────────────────────────────────────────────────

    def lookup_symbol(self, symbol_name: str) -> list[dict]:
        """O(1) reverse-index lookup. Returns [{'file': str, 'line': int}]."""
        entries = self.index_data["reverse_index"].get(symbol_name, [])
        return [{"file": f, "line": l} for f, l in entries]

    def get_symbol_table(self, file_path: str) -> SymbolTable:
        """Return a SymbolTable for bisect-based line-range queries."""
        return build_symbol_table_from_index(file_path, self.index_data)

    # ── persistence ───────────────────────────────────────────────────────────

    def save(self) -> None:
        os.makedirs(os.path.dirname(AST_INDEX_FILE), exist_ok=True)
        with open(AST_INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(self.index_data, f, indent=2)
        if self.faiss_index is not None:
            faiss.write_index(self.faiss_index, AST_FAISS_FILE)
        with open(AST_META_FILE, "w", encoding="utf-8") as f:
            json.dump(self.faiss_meta, f, indent=2)

    def load(self) -> None:
        """Load existing index from disk. Silently does nothing if not present."""
        if os.path.exists(AST_INDEX_FILE):
            with open(AST_INDEX_FILE, encoding="utf-8") as f:
                self.index_data = json.load(f)
        if os.path.exists(AST_FAISS_FILE):
            self.faiss_index = faiss.read_index(AST_FAISS_FILE)
        else:
            self._ensure_faiss()
        if os.path.exists(AST_META_FILE):
            with open(AST_META_FILE, encoding="utf-8") as f:
                self.faiss_meta = json.load(f)
        self._loaded = True
