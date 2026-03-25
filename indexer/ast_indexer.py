"""
AST indexer — walks a Python repo, extracts symbols, embeds them into a
separate FAISS index, and builds a reverse index (symbol → [(file, line)]).

FAISS index type: IndexIDMap2(IndexFlatL2(384))
  — unlike semantic.index (IndexFlatL2) this supports remove_ids() so
    individual files can be cleanly re-indexed without a full rebuild.

Persistence:
  .cognirepo/index/ast_index.json     — full index + reverse_index dict
  .cognirepo/index/ast.index          — FAISS index
  .cognirepo/index/ast_metadata.json  — parallel metadata list (faiss_id → record)
"""
import ast
import hashlib
import json
import os
from datetime import datetime, timezone

import faiss
import numpy as np

from graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType
from graph.graph_utils import make_node_id, node_id_from_symbol_record
from indexer.index_utils import SymbolRecord, SymbolTable, build_symbol_table_from_index
from memory.embeddings import get_model

AST_INDEX_FILE = ".cognirepo/index/ast_index.json"
AST_FAISS_FILE = ".cognirepo/index/ast.index"
AST_META_FILE  = ".cognirepo/index/ast_metadata.json"

_SKIP_DIRS = {".git", "venv", "__pycache__", ".cognirepo", "node_modules", ".mypy_cache"}


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class ASTIndexer:
    """Index a Python repo: extract symbols → embed → FAISS + reverse index."""

    def __init__(self, graph: KnowledgeGraph) -> None:
        self.graph = graph
        self.model = get_model()
        self.faiss_index: faiss.Index | None = None
        self.faiss_meta: list[dict] = []
        self.index_data: dict = {
            "version": 1,
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

    # ── public API ────────────────────────────────────────────────────────────

    def index_repo(self, repo_root: str) -> dict:
        """
        Walk repo_root, index every .py file (skipping _SKIP_DIRS), build the
        reverse index, and save everything to disk.
        Returns a summary dict.
        """
        self._ensure_faiss()
        repo_root = os.path.abspath(repo_root)
        self.index_data["repo_root"] = repo_root
        self.index_data["indexed_at"] = _now()

        count = 0
        for dirpath, dirnames, filenames in os.walk(repo_root):
            # prune skip dirs in-place
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in filenames:
                if not fname.endswith(".py"):
                    continue
                abs_path = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(abs_path, repo_root)
                try:
                    self.index_file(rel_path, abs_path)
                    count += 1
                except Exception as exc:  # pylint: disable=broad-except
                    print(f"  [skip] {rel_path}: {exc}")

        self._build_reverse_index()
        self.index_data["total_symbols"] = sum(
            len(f.get("symbols", [])) for f in self.index_data["files"].values()
        )
        self.save()
        print(f"Indexed {count} files, {self.index_data['total_symbols']} symbols.")
        return {"files": count, "symbols": self.index_data["total_symbols"]}

    def index_file(self, rel_path: str, abs_path: str | None = None) -> dict:
        """
        Index one file. Skips if sha256 matches existing entry.
        Returns the file record dict.
        """
        self._ensure_faiss()
        if abs_path is None:
            abs_path = rel_path  # caller is responsible if relative

        sha = _sha256(abs_path)
        existing = self.index_data["files"].get(rel_path, {})
        if existing.get("sha256") == sha:
            return existing  # unchanged — skip

        with open(abs_path, encoding="utf-8", errors="ignore") as f:
            source = f.read()

        try:
            tree = ast.parse(source, filename=abs_path)
        except SyntaxError:
            return {}

        raw_symbols = self._extract_symbols(tree, rel_path)

        # remove old FAISS entries for this file
        old_ids = [s["faiss_id"] for s in existing.get("symbols", []) if s.get("faiss_id", -1) >= 0]
        if old_ids and self.faiss_index is not None:
            try:
                self.faiss_index.remove_ids(np.array(old_ids, dtype=np.int64))
            except Exception:  # pylint: disable=broad-except
                pass  # IndexIDMap2 may not have those IDs on fresh load

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
            "symbols": raw_symbols,
        }
        self.index_data["files"][rel_path] = file_record
        return file_record

    def _extract_symbols(self, tree: ast.AST, file_path: str) -> list[dict]:
        """
        Walk AST and collect FunctionDef, AsyncFunctionDef, ClassDef nodes.
        Returns list of raw symbol dicts sorted by start_line.
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

            # collect call targets (direct names and attribute calls)
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
                "calls": list(dict.fromkeys(calls)),  # deduplicate, preserve order
                "faiss_id": -1,
            })

        symbols.sort(key=lambda s: s["start_line"])
        return symbols

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
        """O(1) reverse-index lookup. Returns [{"file": str, "line": int}]."""
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
