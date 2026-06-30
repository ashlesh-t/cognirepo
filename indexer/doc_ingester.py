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

# Directories to skip when walking the full repo for docs
_SKIP_DIRS = {".git", "venv", ".venv", "__pycache__", "node_modules", ".cognirepo",
              ".tox", ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs"}

# File substrings to skip (mirrors docs_search._SKIP_FILE_SUBSTRINGS)
_SKIP_FILE_SUBSTRINGS = {
    "MANUAL_TEST_SUITE", "TEST_SUITE", "test_suite", "MANUAL_TEST",
    "PULL_REQUEST_TEMPLATE", "ISSUE_TEMPLATE",
    "pull_request_template", "issue_template",
}
# Path fragments for boilerplate directories to skip during ingestion
_SKIP_PATH_FRAGMENTS = {".github", ".gitlab", ".bitbucket"}

# Maximum total chunks across the whole repo (prevents huge monorepos from OOM)
_MAX_TOTAL_CHUNKS = 2000

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
            from data.memory.embeddings import get_model          # pylint: disable=import-outside-toplevel
            from core.vector_db.factory import get_vector_adapter  # pylint: disable=import-outside-toplevel
        except ImportError as exc:
            log.warning("DocIngester: cannot import dependencies (%s) — skipping", exc)
            return {"chunks": 0, "files": 0}

        model = get_model()
        db = get_vector_adapter()

        # Cap total chunks to avoid OOM on very large repos
        if len(chunks) > _MAX_TOTAL_CHUNKS:
            log.info("DocIngester: capping %d chunks to %d", len(chunks), _MAX_TOTAL_CHUNKS)
            chunks = chunks[:_MAX_TOTAL_CHUNKS]

        # Dedup by normalized text — re-running ingestion (or the historical
        # double-invocation from inside index_repo) must not store the same
        # chunk twice.
        seen_norm: set[str] = set()
        unique_chunks: list[dict] = []
        for chunk in chunks:
            norm = " ".join(chunk["text"].split())
            if norm in seen_norm:
                continue
            seen_norm.add(norm)
            unique_chunks.append(chunk)
        chunks = unique_chunks

        # One streamed batch pass instead of N separate model.embed([one])
        # calls — thousands of individual ONNX invocations in an already
        # memory-heavy process were implicated in a native segfault at the
        # end of large-repo indexing runs.
        batch: list[tuple] = []
        try:
            texts = [c["text"] for c in chunks]
            for chunk, vec in zip(chunks, model.embed(texts, batch_size=64)):
                # Use the actual relative file path as source so search_docs can
                # apply _should_skip_file() correctly; fall back to "init_doc" for
                # chunks without a traceable path (e.g. git log).
                chunk_source = chunk.get("source") or "init_doc"
                batch.append((vec.astype("float32"), chunk["text"], 0.6, chunk_source))
        except Exception as exc:  # pylint: disable=broad-except
            log.warning("DocIngester: batch embed failed (%s) — storing %d chunk(s) embedded so far", exc, len(batch))

        stored = db.add_batch(batch)
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

    @staticmethod
    def _should_skip_file(path: str) -> bool:
        basename = os.path.basename(path)
        if any(sub in basename for sub in _SKIP_FILE_SUBSTRINGS):
            return True
        norm = path.replace("\\", "/")
        return any(frag in norm for frag in _SKIP_PATH_FRAGMENTS)

    def _find_doc_files(self) -> list[str]:
        found: list[str] = []

        # Root-level priority docs (always included if present)
        for pattern in _ROOT_DOC_PATTERNS:
            candidate = os.path.join(self.root, pattern)
            if os.path.isfile(candidate) and not self._should_skip_file(candidate):
                found.append(candidate)
            candidate_lower = os.path.join(self.root, pattern.lower())
            if (candidate_lower != candidate and os.path.isfile(candidate_lower)
                    and not self._should_skip_file(candidate_lower)):
                found.append(candidate_lower)

        # Full repo walk — picks up ALL .md and .rst files (e.g. ansible's changelogs/,
        # kubernetes' docs/, etc.) that would otherwise be missed by the subdirs-only scan.
        # Apply the same skip filters as search_docs to avoid test-suite contamination.
        for dirpath, dirnames, files in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in files:
                if not fname.lower().endswith((".md", ".rst")):
                    continue
                fpath = os.path.join(dirpath, fname)
                if not self._should_skip_file(fpath):
                    found.append(fpath)

        # Deduplicate preserving order (priority files first)
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


def run_ingest_subprocess(project_root: str, timeout: int = 900) -> dict:
    """Run DocIngester in a fresh interpreter; fall back to in-process.

    After a large indexing run the parent process holds fragmented native
    heaps (ONNX + FAISS) — running ingestion there was observed to segfault.
    A clean subprocess is immune, and a native crash becomes a contained
    non-zero exit code instead of killing the whole index run.
    """
    import json as _json  # pylint: disable=import-outside-toplevel
    import sys as _sys  # pylint: disable=import-outside-toplevel
    root = os.path.abspath(project_root)
    try:
        for attempt in (1, 2):
            proc = subprocess.run(
                [_sys.executable, "-m", "indexer.doc_ingester", root],
                capture_output=True, text=True, timeout=timeout,
                cwd=root,  # so config/paths resolves the project's .cognirepo/
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return _json.loads(proc.stdout.strip().splitlines()[-1])
            if proc.returncode in (-11, 139) and attempt == 1:
                # Native segfault — a poisoned chroma store crashes chromadb
                # at open. The crashed attempt left the .opening sentinel
                # behind; the retry triggers the factory's quarantine-and-
                # start-fresh self-heal.
                log.warning(
                    "DocIngester subprocess segfaulted (likely a poisoned vector "
                    "store) — quarantining and retrying once…"
                )
                continue
            break
        log.warning(
            "DocIngester subprocess exited rc=%s — doc search may be incomplete. "
            "Re-run: cognirepo index-repo . (stderr tail: %s)",
            proc.returncode, (proc.stderr or "")[-300:],
        )
        return {"chunks": 0, "files": 0, "error": f"subprocess rc={proc.returncode}"}
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        log.debug("DocIngester subprocess unavailable (%s) — running in-process", exc)
        return DocIngester(root).ingest()


# ── subprocess entry point ────────────────────────────────────────────────────
# `python -m indexer.doc_ingester <project_root>` — used by the CLI to run
# ingestion in a FRESH process. After a large tier-2 indexing run the parent
# interpreter holds fragmented native heaps (ONNX + FAISS); running ingestion
# there was observed to segfault. A clean process is immune, and a native
# crash becomes a contained non-zero exit instead of killing the index run.
if __name__ == "__main__":
    import json as _json
    import sys as _sys

    _root = _sys.argv[1] if len(_sys.argv) > 1 else "."
    _result = DocIngester(_root).ingest()
    print(_json.dumps(_result))
