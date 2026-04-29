# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
DocIngester — seeds the semantic memory store on `cognirepo init`.

Solves the cold-start problem: after a fresh init the AST index is populated
with code symbols, but `retrieve_memory` and `context_pack` return nothing
because the FAISS semantic store is empty.

DocIngester scans the project for documentation (READMEs, changelogs, .md
files under docs/) and recent git history, chunks the content, embeds each
chunk, and stores it in the semantic store with source="init_doc".

This means any AI agent using CogniRepo on a fresh repo immediately gets:
  - Project purpose and architecture from README
  - Recent change history from git log / CHANGELOG
  - API / usage docs from docs/ directory

Usage (called automatically by `cognirepo init`):
    from indexer.doc_ingester import DocIngester
    DocIngester(project_root).ingest()
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

# Markdown files to look for at the repo root (case-insensitive glob)
_ROOT_DOC_PATTERNS = [
    "README.md", "README.rst", "README.txt",
    "CHANGELOG.md", "CHANGELOG.rst", "CHANGES.md",
    "CONTRIBUTING.md", "CONTRIBUTING.rst",
    "ARCHITECTURE.md", "DESIGN.md",
    "USAGE.md", "FEATURE.md",
]

# Subdirectories to scan for additional .md files
_DOC_SUBDIRS = ["docs", "doc", "documentation", "wiki"]

# Maximum characters per chunk (roughly 400–500 tokens for MiniLM)
_CHUNK_MAX_CHARS = 1800

# Minimum characters to bother embedding (avoids empty headings)
_CHUNK_MIN_CHARS = 60

# Maximum chunks per single file (prevents one giant doc from dominating)
_MAX_CHUNKS_PER_FILE = 30

# Maximum git log lines to embed
_GIT_LOG_LINES = 120


class DocIngester:
    """
    Scans project documentation and git history, embeds content, and seeds
    the semantic vector store so retrieve_memory() works from day one.
    """

    def __init__(self, project_root: str) -> None:
        self.root = os.path.abspath(project_root)

    # ── public entry point ────────────────────────────────────────────────────

    def ingest(self) -> dict:
        """
        Scan docs + git log, embed chunks, store in semantic DB.
        Returns a summary dict with counts.
        Returns early (empty summary) if no content is found.
        """
        chunks = self._collect_chunks()
        if not chunks:
            log.debug("DocIngester: no documentation found to ingest")
            return {"chunks": 0, "files": 0}

        try:
            from memory.embeddings import get_model          # pylint: disable=import-outside-toplevel
            from vector_db.local_vector_db import LocalVectorDB  # pylint: disable=import-outside-toplevel
        except ImportError as exc:
            log.warning("DocIngester: cannot import dependencies (%s) — skipping", exc)
            return {"chunks": 0, "files": 0}

        model = get_model()
        db = LocalVectorDB()

        stored = 0
        for chunk in chunks:
            try:
                vec = next(iter(model.embed([chunk["text"]]))).astype("float32")
                db.add(vec, chunk["text"], importance=0.6, source="init_doc")
                stored += 1
            except Exception as exc:  # pylint: disable=broad-except
                log.debug("DocIngester: failed to embed chunk: %s", exc)

        files_seen = len({c["source"] for c in chunks})
        log.info("DocIngester: stored %d chunks from %d source(s)", stored, files_seen)
        return {"chunks": stored, "files": files_seen}

    # ── collection ────────────────────────────────────────────────────────────

    def _collect_chunks(self) -> list[dict]:
        chunks: list[dict] = []
        chunks.extend(self._doc_chunks())
        chunks.extend(self._git_chunks())
        return chunks

    def _doc_chunks(self) -> list[dict]:
        chunks: list[dict] = []
        for path in self._find_doc_files():
            try:
                text = Path(path).read_text(encoding="utf-8", errors="ignore")
                rel = os.path.relpath(path, self.root)
                for chunk_text in self._chunk_markdown(text):
                    chunks.append({"text": chunk_text, "source": rel})
            except OSError:
                pass
        return chunks

    def _git_chunks(self) -> list[dict]:
        """Embed recent git log as context about project evolution."""
        try:
            result = subprocess.run(
                ["git", "-C", self.root, "log", "--oneline", f"-{_GIT_LOG_LINES}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return []
        except (OSError, subprocess.TimeoutExpired):
            return []

        lines = result.stdout.strip().splitlines()
        # Group into blocks of 20 lines so each chunk stays under token limit
        block_size = 20
        chunks = []
        for i in range(0, len(lines), block_size):
            block = "\n".join(lines[i:i + block_size])
            text = f"Git history (recent commits):\n{block}"
            chunks.append({"text": text, "source": "git:log"})
        return chunks

    # ── file discovery ────────────────────────────────────────────────────────

    def _find_doc_files(self) -> list[str]:
        found: list[str] = []

        # Root-level docs
        for pattern in _ROOT_DOC_PATTERNS:
            candidate = os.path.join(self.root, pattern)
            if os.path.isfile(candidate):
                found.append(candidate)
            # also check lowercase variant
            candidate_lower = os.path.join(self.root, pattern.lower())
            if candidate_lower != candidate and os.path.isfile(candidate_lower):
                found.append(candidate_lower)

        # docs/ subdirectory .md files
        for subdir in _DOC_SUBDIRS:
            docs_dir = os.path.join(self.root, subdir)
            if not os.path.isdir(docs_dir):
                continue
            for dirpath, _dirs, files in os.walk(docs_dir):
                for fname in files:
                    if fname.lower().endswith((".md", ".rst", ".txt")):
                        found.append(os.path.join(dirpath, fname))

        # deduplicate preserving order
        seen: set[str] = set()
        result: list[str] = []
        for f in found:
            key = os.path.realpath(f)
            if key not in seen:
                seen.add(key)
                result.append(f)
        return result

    # ── chunking ──────────────────────────────────────────────────────────────

    def _chunk_markdown(self, text: str) -> list[str]:
        """
        Split a markdown document into semantic chunks.

        Strategy:
        1. Split on ## headings — each section becomes a candidate chunk.
        2. If a section exceeds _CHUNK_MAX_CHARS, split further on
           paragraph breaks (blank lines).
        3. Skip chunks that are too short (headings with no body).
        4. Cap at _MAX_CHUNKS_PER_FILE chunks per file.
        """
        # Split on H2+ headings (## or ###)
        sections = re.split(r"(?m)^#{2,}\s+", text)
        chunks: list[str] = []

        for section in sections:
            section = section.strip()
            if not section:
                continue
            if len(section) <= _CHUNK_MAX_CHARS:
                if len(section) >= _CHUNK_MIN_CHARS:
                    chunks.append(section)
            else:
                # Split large section on blank lines (paragraph breaks)
                paragraphs = re.split(r"\n{2,}", section)
                current = ""
                for para in paragraphs:
                    para = para.strip()
                    if not para:
                        continue
                    if len(current) + len(para) + 2 <= _CHUNK_MAX_CHARS:
                        current = (current + "\n\n" + para).strip()
                    else:
                        if len(current) >= _CHUNK_MIN_CHARS:
                            chunks.append(current)
                        current = para
                if len(current) >= _CHUNK_MIN_CHARS:
                    chunks.append(current)

            if len(chunks) >= _MAX_CHUNKS_PER_FILE:
                break

        return chunks[:_MAX_CHUNKS_PER_FILE]
