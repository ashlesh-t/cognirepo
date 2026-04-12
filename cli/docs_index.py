# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Tier-1 embedded docs index — answers CogniRepo usage questions locally,
with zero API calls.

Build:
    build_docs_index(dest)  — chunks .md files, embeds with all-MiniLM-L6-v2,
                              saves FAISS + BM25 + JSON metadata under dest/

Query:
    DocsIndex.answer(query, top_k=3) → list[{file, section, score, text}]

Confidence-threshold routing (Decision #6):
    score >= 0.6  → return local answer (Tier-1, zero API cost)
    score <  0.6  → caller should promote to QUICK tier
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CONFIDENCE_THRESHOLD = 0.6
_CHUNK_TOKENS = 200           # approximate target chunk size in words
_DOCS_QUERY_KEYWORDS = re.compile(
    r"\b(cognirepo|install|tier|mcp|prune|doctor|serve.api|retrieve|store|"
    r"how does|what is cognirepo|index.repo|memory|graph|embedding)\b",
    re.IGNORECASE,
)

# Source docs shipped in the wheel (relative paths from repo root)
_DOC_SOURCES = [
    "USAGE.md",
    "ARCHITECTURE.md",
    "README.md",
    "LANGUAGES.md",
    "FEATURE.md",
]


def _global_index_dir() -> Path:
    base = os.environ.get("COGNIREPO_GLOBAL_DIR", str(Path.home() / ".cognirepo"))
    return Path(base) / "docs_index"


def _chunk_markdown(path: Path, chunk_words: int = _CHUNK_TOKENS) -> list[dict]:
    """Split a markdown file into chunks of ~chunk_words words each."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    # Split on headings
    sections = re.split(r"(?m)^(#{1,3} .+)$", text)
    chunks: list[dict] = []
    current_heading = path.name
    for part in sections:
        part = part.strip()
        if not part:
            continue
        if re.match(r"^#{1,3} ", part):
            current_heading = part.lstrip("# ").strip()
            continue
        # Split long sections into word-bounded chunks
        words = part.split()
        for i in range(0, max(1, len(words)), chunk_words):
            chunk_text = " ".join(words[i:i + chunk_words])
            if len(chunk_text) < 20:
                continue
            chunks.append({
                "file": path.name,
                "section": current_heading,
                "text": chunk_text,
            })
    return chunks


def build_docs_index(dest: Path, doc_roots: Optional[list[Path]] = None) -> int:
    """
    Build the docs index under dest/.

    Parameters
    ----------
    dest       : output directory (created if absent)
    doc_roots  : list of directories to search for .md files.
                 Defaults to the cognirepo package _docs/ dir + cwd.

    Returns the number of chunks indexed.
    """
    import faiss  # pylint: disable=import-outside-toplevel
    from memory.embeddings import get_model  # pylint: disable=import-outside-toplevel

    dest.mkdir(parents=True, exist_ok=True)

    # Collect markdown files
    if doc_roots is None:
        repo_root = Path(__file__).parent.parent
        doc_roots = [repo_root]

    all_chunks: list[dict] = []
    for root in doc_roots:
        for name in _DOC_SOURCES:
            path = root / name
            all_chunks.extend(_chunk_markdown(path))
        # Also index docs/ subdirectory
        docs_dir = root / "docs"
        if docs_dir.exists():
            for md in docs_dir.rglob("*.md"):
                all_chunks.extend(_chunk_markdown(md))

    if not all_chunks:
        logger.warning("docs_index: no .md chunks found")
        return 0

    # Embed
    model = get_model()
    texts = [c["text"] for c in all_chunks]
    t0 = time.perf_counter()
    vectors = model.encode(texts, normalize_embeddings=True).astype("float32")
    logger.info("docs_index: embedded %d chunks in %.1fs", len(texts), time.perf_counter() - t0)

    # FAISS
    dim = vectors.shape[1]
    index = faiss.IndexFlatIP(dim)   # inner product on normalised = cosine
    index.add(vectors)
    faiss.write_index(index, str(dest / "docs.index"))

    # Metadata
    (dest / "docs_meta.json").write_text(
        json.dumps(all_chunks, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Record mtimes of source files so we can skip rebuilds
    mtimes = {}
    for root in doc_roots:
        for name in _DOC_SOURCES:
            p = root / name
            if p.exists():
                mtimes[str(p)] = p.stat().st_mtime
    (dest / "docs_mtimes.json").write_text(json.dumps(mtimes), encoding="utf-8")

    logger.info("docs_index: built %d chunks under %s", len(all_chunks), dest)
    return len(all_chunks)


def _index_is_stale(dest: Path, doc_roots: list[Path]) -> bool:
    """Return True if any source .md file is newer than the stored index."""
    mtimes_path = dest / "docs_mtimes.json"
    if not (dest / "docs.index").exists() or not mtimes_path.exists():
        return True
    try:
        stored = json.loads(mtimes_path.read_text())
        for root in doc_roots:
            for name in _DOC_SOURCES:
                p = root / name
                if p.exists():
                    if str(p) not in stored or p.stat().st_mtime > stored[str(p)]:
                        return True
    except Exception:  # pylint: disable=broad-except
        return True
    return False


class DocsIndex:
    """Query interface for the pre-built docs FAISS index."""

    def __init__(self, dest: Path) -> None:
        import faiss  # pylint: disable=import-outside-toplevel
        self._index = faiss.read_index(str(dest / "docs.index"))
        meta_raw = (dest / "docs_meta.json").read_text(encoding="utf-8")
        self._meta: list[dict] = json.loads(meta_raw)

    def answer(self, query: str, top_k: int = 3) -> list[dict]:
        """
        Return top_k results with their cosine similarity scores.
        Each result: {file, section, score, text}
        """
        from memory.embeddings import get_model  # pylint: disable=import-outside-toplevel
        model = get_model()
        vec = model.encode(query, normalize_embeddings=True).astype("float32").reshape(1, -1)
        k = min(top_k, self._index.ntotal)
        if k == 0:
            return []
        scores, indices = self._index.search(vec, k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._meta):
                continue
            chunk = dict(self._meta[idx])
            chunk["score"] = float(score)
            results.append(chunk)
        return results

    def is_docs_query(self, query: str) -> bool:
        """Heuristic: does this look like a CogniRepo usage question?"""
        return bool(_DOCS_QUERY_KEYWORDS.search(query))


def ensure_docs_index(doc_roots: Optional[list[Path]] = None) -> Optional[DocsIndex]:
    """
    Ensure the docs index is built (build if missing or stale).
    Returns a DocsIndex instance, or None on error.
    """
    dest = _global_index_dir()
    roots = doc_roots or [Path(__file__).parent.parent]

    if _index_is_stale(dest, roots):
        logger.info("docs_index: building (one-time, may take ~3s)…")
        try:
            build_docs_index(dest, roots)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("docs_index: build failed: %s", exc)
            return None

    try:
        return DocsIndex(dest)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("docs_index: load failed: %s", exc)
        return None
