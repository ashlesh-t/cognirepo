"""
Module for searching through markdown files in the repository.

Search strategy (two-pass):
  1. Reverse-index fast path: extract tokens from query, look up in
     ast_index.json reverse_index for matching .md entries — O(1) per token.
  2. Full-text fallback: original os.walk + substring match, always runs
     to catch docs that haven't been AST-indexed.

Results are deduplicated.
"""
import json
import os

AST_INDEX_FILE = ".cognirepo/index/ast_index.json"


def search_docs(query: str) -> list[str]:
    """
    Search for a query string in all .md files.
    Returns a list of matching file paths.
    """
    results: list[str] = []
    seen: set[str] = set()

    # ── fast path: reverse index ──────────────────────────────────────────────
    if os.path.exists(AST_INDEX_FILE):
        try:
            with open(AST_INDEX_FILE, encoding="utf-8") as f:
                idx = json.load(f)
            rev = idx.get("reverse_index", {})
            for token in query.lower().split():
                for entry in rev.get(token, []):
                    file_path = entry[0] if isinstance(entry, list) else entry
                    if file_path.endswith(".md") and file_path not in seen:
                        seen.add(file_path)
                        results.append(file_path)
        except (json.JSONDecodeError, OSError, IndexError):
            pass  # fall through to full-text scan

    # ── full-text fallback ────────────────────────────────────────────────────
    for root, dirnames, files in os.walk("."):
        # skip noise dirs
        dirnames[:] = [d for d in dirnames if d not in {".git", "venv", "__pycache__"}]
        for fname in files:
            if not fname.endswith(".md"):
                continue
            path = os.path.join(root, fname)
            if path in seen:
                continue
            with open(path, "r", encoding="utf-8", errors="ignore") as file:
                if query.lower() in file.read().lower():
                    seen.add(path)
                    results.append(path)

    return results
