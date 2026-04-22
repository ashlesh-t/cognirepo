# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Hierarchical Summarization Engine — 100% local, zero API calls.

Builds a structured summary tree from the existing AST index:
  - Level 1: File summaries  (symbols + docstrings already in ast_index.json)
  - Level 2: Directory summaries  (rolled up from children)
  - Level 3: Repository summary   (rolled up from directories)

Each summary is also embedded into FAISS so `architecture_overview` queries
hit the same vector index as code symbols — no separate search path needed.

No LLM. No API key. Runs in < 1 second on most repos.
"""
import json
import os
import logging
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)


def _first_sentence(text: str) -> str:
    """Extract the first meaningful sentence from a docstring."""
    if not text:
        return ""
    # strip triple-quote noise
    text = text.strip().strip('"\'').strip()
    # take up to first period or newline
    for sep in (".\n", "\n\n", ". ", "\n"):
        idx = text.find(sep)
        if 0 < idx < 200:
            return text[: idx + 1].strip()
    return text[:160].strip()


def _build_file_summary(rel_path: str, file_data: dict) -> dict:
    """Build a structured summary for one file from its AST record.

    Returns a dict with: path, language, classes, functions, constants,
    purpose (from first docstring), line_count, symbol_count.
    """
    symbols = file_data.get("symbols", [])
    language = file_data.get("language", "unknown")

    classes: list[str] = []
    functions: list[str] = []
    constants: list[str] = []
    purpose = ""

    for sym in symbols:
        stype = sym.get("type", "")
        name = sym.get("name", "")
        doc = sym.get("docstring", "") or ""

        if stype == "CLASS":
            classes.append(name)
            if not purpose:
                purpose = _first_sentence(doc)
        elif stype == "FUNCTION":
            # skip dunders for the summary (keep API surface clean)
            if not (name.startswith("__") and name.endswith("__")):
                functions.append(name)
            if not purpose:
                purpose = _first_sentence(doc)
        elif stype in ("CONSTANT", "VARIABLE"):
            if name.isupper():  # only module-level constants
                constants.append(name)

    # line count approximation from last symbol
    line_count = 0
    if symbols:
        line_count = max(s.get("end_line", 0) for s in symbols)

    return {
        "path": rel_path,
        "language": language,
        "purpose": purpose,
        "classes": classes[:10],
        "functions": functions[:15],
        "constants": constants[:8],
        "symbol_count": len(symbols),
        "line_count": line_count,
        # human-readable one-liner for architecture_overview output
        "summary": _format_file_oneliner(rel_path, purpose, classes, functions),
    }


def _format_file_oneliner(
    rel_path: str,
    purpose: str,
    classes: list[str],
    functions: list[str],
) -> str:
    parts = [f"`{rel_path}`"]
    if purpose:
        parts.append(f"— {purpose}")
    if classes:
        parts.append(f"  Classes: {', '.join(classes[:5])}")
    if functions:
        parts.append(f"  Functions: {', '.join(functions[:8])}")
    return " ".join(parts)


def _build_dir_summary(rel_dir: str, child_file_summaries: list[dict]) -> dict:
    """Roll up file summaries into a directory-level summary."""
    all_classes: list[str] = []
    all_functions: list[str] = []
    file_count = len(child_file_summaries)
    languages: dict[str, int] = defaultdict(int)

    for fs in child_file_summaries:
        all_classes.extend(fs.get("classes", []))
        all_functions.extend(fs.get("functions", []))
        lang = fs.get("language", "")
        if lang and lang != "unknown":
            languages[lang] += 1

    top_classes = list(dict.fromkeys(all_classes))[:10]
    top_functions = list(dict.fromkeys(all_functions))[:15]
    dominant_lang = max(languages, key=languages.get) if languages else "unknown"

    label = rel_dir if rel_dir else "<root>"
    summary_parts = [f"`{label}/`", f"{file_count} file(s)"]
    if top_classes:
        summary_parts.append(f"Classes: {', '.join(top_classes[:5])}")
    if top_functions:
        summary_parts.append(f"Functions: {', '.join(top_functions[:8])}")

    return {
        "path": rel_dir,
        "file_count": file_count,
        "dominant_language": dominant_lang,
        "top_classes": top_classes,
        "top_functions": top_functions,
        "summary": " | ".join(summary_parts),
    }


def _build_repo_summary(repo_name: str, dir_summaries: list[dict], file_summaries: list[dict]) -> str:
    """Build the top-level repository summary string."""
    total_files = sum(d.get("file_count", 0) for d in dir_summaries)
    total_symbols = sum(f.get("symbol_count", 0) for f in file_summaries)

    # Collect all classes and functions across the whole repo
    all_classes: list[str] = []
    all_functions: list[str] = []
    for d in dir_summaries:
        all_classes.extend(d.get("top_classes", []))
        all_functions.extend(d.get("top_functions", []))

    top_classes = list(dict.fromkeys(all_classes))[:12]
    top_functions = list(dict.fromkeys(all_functions))[:15]
    top_dirs = [d["path"] for d in dir_summaries if d["path"]][:8]

    lines = [
        f"Repository: {repo_name}",
        f"  {total_files} source files | {total_symbols} symbols",
    ]
    if top_dirs:
        lines.append(f"  Top packages: {', '.join(top_dirs)}")
    if top_classes:
        lines.append(f"  Key classes: {', '.join(top_classes[:8])}")
    if top_functions:
        lines.append(f"  Key functions: {', '.join(top_functions[:10])}")

    return "\n".join(lines)


class SummarizationEngine:
    def __init__(self, project_root: str = "."):
        self.project_root = os.path.abspath(project_root)

    def summarize_file(
        self,
        rel_path: str,
        file_data: dict | None = None,
    ) -> dict:
        """Build a structured summary dict for one file.

        file_data: pre-loaded record from ast_index.json.
        If None, loads the indexer from disk (standalone use only).
        """
        if file_data is None:
            from indexer.ast_indexer import ASTIndexer  # pylint: disable=import-outside-toplevel
            from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
            kg = KnowledgeGraph()
            indexer = ASTIndexer(graph=kg)
            indexer.load()
            file_data = indexer.index_data.get("files", {}).get(rel_path, {})
        return _build_file_summary(rel_path, file_data or {})

    def run_full_summarization(self) -> dict:
        """
        Build the full summary tree from the local AST index.

        No LLM calls. No API key required. Pure local from ast_index.json.
        Also embeds file summary text into FAISS so architecture queries
        land in the same vector index as code symbols.

        Stores result in .cognirepo/index/summaries.json.
        """
        from indexer.ast_indexer import ASTIndexer  # pylint: disable=import-outside-toplevel
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel

        # Load once — shared across all files
        kg = KnowledgeGraph()
        indexer = ASTIndexer(graph=kg)
        indexer.load()

        all_files = indexer.index_data.get("files", {})
        if not all_files:
            logger.warning("No indexed files — run 'cognirepo index-repo .' first.")
            return {"repo": "", "directories": {}, "files": {}}

        print(f"Building summaries for {len(all_files)} indexed files (local, no API)…")

        # ── Level 1: file summaries ───────────────────────────────────────────
        file_summaries: dict[str, dict] = {}
        for rel_path, file_data in all_files.items():
            fs = _build_file_summary(rel_path, file_data)
            if fs["symbol_count"] > 0:
                file_summaries[rel_path] = fs

        # ── Level 2: directory summaries ─────────────────────────────────────
        # Group files by their immediate parent directory
        dir_to_files: dict[str, list[dict]] = defaultdict(list)
        for rel_path, fs in file_summaries.items():
            parent = str(Path(rel_path).parent)
            if parent == ".":
                parent = ""
            dir_to_files[parent].append(fs)

        dir_summaries: dict[str, dict] = {}
        for rel_dir, child_files in dir_to_files.items():
            dir_summaries[rel_dir] = _build_dir_summary(rel_dir, child_files)

        # ── Level 3: repo summary ─────────────────────────────────────────────
        repo_name = os.path.basename(self.project_root)
        repo_summary = _build_repo_summary(
            repo_name,
            list(dir_summaries.values()),
            list(file_summaries.values()),
        )

        # ── Embed file summaries into FAISS for semantic search ───────────────
        self._embed_summaries(indexer, file_summaries)

        result = {
            "repo": repo_summary,
            "directories": {k: v["summary"] for k, v in dir_summaries.items()},
            "files": {k: v["summary"] for k, v in file_summaries.items()},
            # Full structured data (for tooling that wants more detail)
            "_structured": {
                "files": file_summaries,
                "directories": dir_summaries,
            },
        }

        save_path = os.path.join(self.project_root, ".cognirepo", "index", "summaries.json")
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        print(
            f"  Done: {len(file_summaries)} files, "
            f"{len(dir_summaries)} directories. "
            f"Saved to .cognirepo/index/summaries.json"
        )
        return result

    def _embed_summaries(self, indexer, file_summaries: dict[str, dict]) -> None:
        """Embed file summary text into the AST FAISS index.

        This makes `semantic_search_code` and `context_pack` able to match
        architecture questions (e.g. "where is auth handled?") to the right
        files via the existing vector index — no separate summary search path.
        """
        try:
            import numpy as np  # pylint: disable=import-outside-toplevel
            from memory.embeddings import get_model  # pylint: disable=import-outside-toplevel

            model = get_model()
            indexer._ensure_faiss()

            for rel_path, fs in file_summaries.items():
                # Build embed text from structured summary
                parts = ["FILE_SUMMARY", os.path.basename(rel_path)]
                if fs.get("purpose"):
                    parts.append(fs["purpose"])
                if fs.get("classes"):
                    parts.append(f"classes: {' '.join(fs['classes'][:6])}")
                if fs.get("functions"):
                    parts.append(f"functions: {' '.join(fs['functions'][:8])}")
                embed_text = " ".join(parts)

                vec = model.encode(embed_text).astype("float32")
                faiss_id = len(indexer.faiss_meta)
                import faiss as _faiss  # pylint: disable=import-outside-toplevel
                import numpy as _np  # pylint: disable=import-outside-toplevel
                indexer.faiss_index.add_with_ids(
                    _np.array([vec], dtype="float32"),
                    _np.array([faiss_id], dtype=_np.int64),
                )
                indexer.faiss_meta.append({
                    "name": os.path.basename(rel_path),
                    "type": "FILE_SUMMARY",
                    "file": rel_path,
                    "start_line": 1,
                    "docstring": fs.get("purpose", ""),
                    "source": "file_summary",
                })

            # Save updated FAISS index and metadata
            indexer.save()
            logger.debug("Embedded %d file summaries into FAISS.", len(file_summaries))
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Summary embedding skipped: %s", exc)
