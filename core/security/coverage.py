# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Single source of truth for which on-disk stores ``storage.encrypt: true`` covers (#186).

Every ``get_path() with a string literal`` in the code base must appear in ``STORE_COVERAGE``;
``tests/test_encryption_coverage.py`` fails when a store is added without being classified,
and ``cognirepo doctor`` / ``SECURITY.md`` read from here so docs and behaviour cannot drift.

Statuses:
  ``encrypted``      — Fernet-encrypted when ``storage.encrypt`` is on.
  ``not_encrypted``  — holds user/code text or embeddings but is NOT covered (see ``note``).
  ``no_content``     — operational state (locks, progress, timestamps, config): nothing to protect.
"""
from __future__ import annotations

ENCRYPTED = "encrypted"
NOT_ENCRYPTED = "not_encrypted"
NO_CONTENT = "no_content"

_EMBED = "embeddings only (no text) — vectors can still leak meaning"
_AST = "symbol names/paths/docstrings; rebuildable from the source tree beside it"

# key = the literal passed to get_path(); value = (status, note)
STORE_COVERAGE: dict[str, tuple[str, str]] = {
    # ── encrypted ────────────────────────────────────────────────────────────
    "graph/graph.pkl":               (ENCRYPTED, "knowledge graph"),
    "graph/graph.journal":           (ENCRYPTED, "graph write-ahead journal"),
    "graph/behaviour.json":          (ENCRYPTED, "behaviour model"),
    "memory/episodic.json":          (ENCRYPTED, "episodic log"),
    "episodic/episodic.json":        (ENCRYPTED, "episodic log"),
    "memory/semantic_metadata.json": (ENCRYPTED, "memory text (local FAISS backend only)"),
    "learnings":                     (ENCRYPTED, "project learnings (global learnings use their own key)"),
    # ── NOT encrypted ────────────────────────────────────────────────────────
    "vector_db/chroma":              (NOT_ENCRYPTED, "DEFAULT backend: memory text + embeddings; Chroma has no encryption hook — use disk encryption"),
    "vector_db/semantic.index":      (NOT_ENCRYPTED, _EMBED),
    "vector_db/semantic.gen":        (NOT_ENCRYPTED, _EMBED),
    "vector_db":                     (NOT_ENCRYPTED, _EMBED),
    "memory/episodic_vecs.npy":      (NOT_ENCRYPTED, _EMBED),
    "memory/episodic_vecs_ids.json": (NOT_ENCRYPTED, "event ids only"),
    "memory/episodic_archive.json":  (NOT_ENCRYPTED, "rotated-out episodic events (text)"),
    "index/ast_index.json":          (NOT_ENCRYPTED, _AST),
    "index/ast_metadata.json":       (NOT_ENCRYPTED, _AST),
    "index/ast.index":               (NOT_ENCRYPTED, _EMBED),
    "index/ast.gen":                 (NOT_ENCRYPTED, _AST),
    "index/manifest.json":           (NOT_ENCRYPTED, "index checksums"),
    "index/summaries.json":          (NOT_ENCRYPTED, "LLM-written summaries of your code"),
    "index/doc_ingest.json":         (NOT_ENCRYPTED, "ingested documentation text"),
    "index/endpoints.json":          (NOT_ENCRYPTED, "HTTP routes found in your code"),
    "index/http_calls.json":         (NOT_ENCRYPTED, "HTTP calls found in your code"),
    "sessions":                      (NOT_ENCRYPTED, "session snapshots / last context"),
    "errors":                        (NOT_ENCRYPTED, "recorded error log"),
    "docs":                          (NOT_ENCRYPTED, "generated documentation"),
    "archive":                       (NOT_ENCRYPTED, "archived/pruned records"),
    "stdlib":                        (NOT_ENCRYPTED, "cached stdlib symbol data (public)"),
    # ── nothing sensitive ────────────────────────────────────────────────────
    "config.json":                   (NO_CONTENT, "settings (no secrets — keys live in the OS keychain)"),
    ".gitignore":                    (NO_CONTENT, "ignore rules"),
    "index/pending_tier2.json":      (NO_CONTENT, "work queue"),
    "index/tier2_progress.json":     (NO_CONTENT, "progress counters"),
    "index/tombstones.json":         (NO_CONTENT, "deleted-file markers"),
    "index/reindex.lock":            (NO_CONTENT, "lock file"),
    "index/last_indexed.json":       (NO_CONTENT, "timestamps"),
    "index":                         (NO_CONTENT, "directory"),
    "graph":                         (NO_CONTENT, "directory"),
    "graph/graph.seq":               (NO_CONTENT, "graph change counter (a single integer)"),
    "memory":                        (NO_CONTENT, "directory"),
    "episodic":                      (NO_CONTENT, "directory"),
    "bg_tasks":                      (NO_CONTENT, "background-task bookkeeping"),
    "benchmark_history.jsonl":       (NO_CONTENT, "benchmark numbers"),
}


def unencrypted_stores() -> dict[str, str]:
    """Stores that hold content but are not covered by ``storage.encrypt`` → note."""
    return {k: note for k, (st, note) in STORE_COVERAGE.items() if st == NOT_ENCRYPTED}
