# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Hierarchical Summarization Engine (RAPTOR-like).

Generates rolling summaries:
  - Level 1: File summaries (from AST symbols and docstrings)
  - Level 2: Directory summaries (rolled up from child file summaries)
  - Level 3: Repository summary (rolled up from directory summaries)
"""
import json
import os
import logging
from pathlib import Path
from orchestrator.router import route

logger = logging.getLogger(__name__)

class SummarizationEngine:
    def __init__(self, project_root: str = "."):
        self.project_root = os.path.abspath(project_root)

    def _summarize_text(self, text: str, context: str) -> str:
        """Use an LLM to summarize a block of text."""
        prompt = (
            f"Summarize the following {context}. Focus on architectural role, "
            "key responsibilities, and main exported symbols. "
            "Keep it concise (2-4 sentences).\n\n"
            f"{text}"
        )
        try:
            # Route to appropriate model automatically based on prompt
            response = route(prompt)
            if hasattr(response, "text"):
                return response.text.strip()
            return str(response).strip()
        except Exception as exc:
            logger.error("Summarization failed: %s", exc)
            return ""

    def summarize_file(self, rel_path: str) -> str:
        """Generate a summary for a single file using its AST data."""
        from indexer.ast_indexer import ASTIndexer  # pylint: disable=import-outside-toplevel
        from graph.knowledge_graph import KnowledgeGraph # pylint: disable=import-outside-toplevel
        kg = KnowledgeGraph()
        indexer = ASTIndexer(graph=kg)
        indexer.load()
        
        file_data = indexer.index_data.get("files", {}).get(rel_path, {})
        if not file_data:
            return ""
        
        symbols = [s["name"] for s in file_data.get("symbols", [])]
        symbol_str = ", ".join(symbols[:20])
        
        content = f"File: {rel_path}\nSymbols: {symbol_str}\n"
        return self._summarize_text(content, f"source file '{rel_path}'")

    def summarize_directory(self, rel_path: str, child_summaries: list[str]) -> str:
        """Generate a summary for a directory based on its children's summaries."""
        content = f"Directory: {rel_path}\nChild Summaries:\n" + "\n".join(child_summaries)
        return self._summarize_text(content, f"directory '{rel_path}'")

    def summarize_repo(self, repo_name: str, dir_summaries: list[str]) -> str:
        """Generate a repository-level summary."""
        content = f"Repository: {repo_name}\nTop-level Directory Summaries:\n" + "\n".join(dir_summaries)
        return self._summarize_text(content, f"repository '{repo_name}'")

    def run_full_summarization(self) -> dict:
        """
        Walk the repo and build the hierarchical summary tree.
        Stores results in .cognirepo/index/summaries.json.
        """
        from indexer.ast_indexer import ASTIndexer, _SKIP_DIRS  # pylint: disable=import-outside-toplevel
        from graph.knowledge_graph import KnowledgeGraph # pylint: disable=import-outside-toplevel
        kg = KnowledgeGraph()
        indexer = ASTIndexer(graph=kg)
        indexer.load()
        
        files = list(indexer.index_data.get("files", {}).keys())
        file_summaries = {}
        
        print(f"Generating summaries for {len(files)} files...")
        for f in files:
            summary = self.summarize_file(f)
            if summary:
                file_summaries[f] = summary

        # Build directory tree
        tree = {}
        for f, s in file_summaries.items():
            parts = Path(f).parts
            for i in range(len(parts)):
                d = str(Path(*parts[:i]))
                if d not in tree: tree[d] = {"files": [], "dirs": []}
                if i == len(parts) - 1:
                    tree[d]["files"].append(s)
                else:
                    child_d = str(Path(*parts[:i+1]))
                    if child_d not in tree[d]["dirs"]:
                        tree[d]["dirs"].append(child_d)

        dir_summaries = {}
        # Bottom-up directory summarization
        sorted_dirs = sorted(tree.keys(), key=lambda x: len(Path(x).parts), reverse=True)
        for d in sorted_dirs:
            children = tree[d]["files"] + [dir_summaries[c] for c in tree[d]["dirs"] if c in dir_summaries]
            if children:
                dir_summaries[d] = self.summarize_directory(d, children)

        repo_name = os.path.basename(self.project_root)
        root_dirs = [dir_summaries[d] for d in dir_summaries if Path(d).parent == Path(".")]
        repo_summary = self.summarize_repo(repo_name, root_dirs)

        result = {
            "repo": repo_summary,
            "directories": dir_summaries,
            "files": file_summaries
        }
        
        save_path = os.path.join(self.project_root, ".cognirepo", "index", "summaries.json")
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
            
        return result
