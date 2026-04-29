# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""Tests for cli/docs_index.py — chunk, build, query, staleness, heuristic."""
from __future__ import annotations
import pytest

import json
from unittest.mock import MagicMock, patch

from cli.docs_index import (
    _CONFIDENCE_THRESHOLD,
    _chunk_markdown,
    _index_is_stale,
    DocsIndex,
    ensure_docs_index,
)


# ── _chunk_markdown ───────────────────────────────────────────────────────────

def test_chunk_markdown_missing_file(tmp_path):
    chunks = _chunk_markdown(tmp_path / "missing.md")
    assert chunks == []


def test_chunk_markdown_basic(tmp_path):
    md = tmp_path / "test.md"
    md.write_text("# Intro\n\nThis is the introduction section with some text words.\n")
    chunks = _chunk_markdown(md, chunk_words=200)
    assert len(chunks) >= 1
    assert chunks[0]["file"] == "test.md"
    assert "introduction" in chunks[0]["text"]


def test_chunk_markdown_splits_large_section(tmp_path):
    """Sections larger than chunk_words should produce multiple chunks."""
    md = tmp_path / "large.md"
    words = " ".join([f"word{i}" for i in range(200)])
    md.write_text(f"# Section\n\n{words}\n")
    chunks = _chunk_markdown(md, chunk_words=50)
    assert len(chunks) >= 3


def test_chunk_markdown_heading_becomes_section(tmp_path):
    md = tmp_path / "headings.md"
    md.write_text(
        "# Installation\n\nInstall using pip install cognirepo.\n\n"
        "## Configuration\n\nConfigure via config.json file.\n"
    )
    chunks = _chunk_markdown(md)
    sections = [c["section"] for c in chunks]
    assert "Installation" in sections
    assert "Configuration" in sections


def test_chunk_markdown_skips_short_chunks(tmp_path):
    """Chunks shorter than 20 chars should be skipped."""
    md = tmp_path / "short.md"
    md.write_text("# Title\n\nHi.\n\n# Another\n\nThis section has enough text to be included.\n")
    chunks = _chunk_markdown(md)
    for c in chunks:
        assert len(c["text"]) >= 20


# ── _index_is_stale ───────────────────────────────────────────────────────────

def test_index_is_stale_missing_index(tmp_path):
    assert _index_is_stale(tmp_path, [tmp_path]) is True


def test_index_is_stale_missing_mtimes(tmp_path):
    (tmp_path / "docs.index").write_text("fake")
    assert _index_is_stale(tmp_path, [tmp_path]) is True


def test_index_is_stale_up_to_date(tmp_path):
    """No source .md files in roots → nothing to compare → not stale."""
    (tmp_path / "docs.index").write_text("fake")
    (tmp_path / "docs_mtimes.json").write_text("{}")
    result = _index_is_stale(tmp_path, [tmp_path])
    assert result is False


def test_index_is_stale_when_file_updated(tmp_path):
    """A source .md newer than stored mtime → stale."""
    md = tmp_path / "README.md"
    md.write_text("hello")
    old_mtime = md.stat().st_mtime - 10
    (tmp_path / "docs.index").write_text("fake")
    (tmp_path / "docs_mtimes.json").write_text(json.dumps({str(md): old_mtime}))
    assert _index_is_stale(tmp_path, [tmp_path]) is True


# ── DocsIndex.is_docs_query ────────────────────────────────────────────────────

def test_is_docs_query_positive():
    idx = object.__new__(DocsIndex)
    assert idx.is_docs_query("how do I install cognirepo")
    assert idx.is_docs_query("what is the MCP tier")
    assert idx.is_docs_query("how does memory work in CogniRepo")


def test_is_docs_query_negative():
    idx = object.__new__(DocsIndex)
    assert not idx.is_docs_query("fix the sort algorithm")
    assert not idx.is_docs_query("calculate fibonacci sequence")


# ── confidence threshold ───────────────────────────────────────────────────────

def test_confidence_threshold_value():
    assert _CONFIDENCE_THRESHOLD == 0.6


# ── ensure_docs_index ─────────────────────────────────────────────────────────

def test_ensure_docs_index_returns_none_on_build_failure(monkeypatch, tmp_path):
    """If build_docs_index raises, ensure_docs_index must return None."""
    monkeypatch.setenv("COGNIREPO_GLOBAL_DIR", str(tmp_path))

    with patch("cli.docs_index.build_docs_index", side_effect=RuntimeError("no faiss")):
        result = ensure_docs_index(doc_roots=[tmp_path])
    assert result is None


# ── DocsIndex.answer via mock ──────────────────────────────────────────────────

def test_docs_index_answer_returns_results(tmp_path):
    """answer() should return chunks sorted by score."""
    import sys
    import numpy as np

    chunks = [
        {"file": "USAGE.md", "section": "Install", "text": "Install with pip install cognirepo."},
        {"file": "README.md", "section": "Intro", "text": "CogniRepo is a local memory engine."},
    ]
    (tmp_path / "docs_meta.json").write_text(json.dumps(chunks))

    fake_faiss_index = MagicMock()
    fake_faiss_index.ntotal = 2
    fake_faiss_index.search.return_value = (
        np.array([[0.9, 0.4]], dtype="float32"),
        np.array([[0, 1]]),
    )

    fake_model = MagicMock()
    fake_model.embed.side_effect = lambda texts: iter([np.zeros(384, dtype="float32") for _ in texts])

    mock_faiss = MagicMock()
    mock_faiss.read_index.return_value = fake_faiss_index

    mock_embeddings = MagicMock()
    mock_embeddings.get_model.return_value = fake_model

    with patch.dict(sys.modules, {"faiss": mock_faiss, "memory.embeddings": mock_embeddings}):
        idx = DocsIndex(tmp_path)

    idx._index = fake_faiss_index
    idx._meta = chunks

    with patch.dict(sys.modules, {"memory.embeddings": mock_embeddings}):
        results = idx.answer("how do I install", top_k=2)

    assert len(results) == 2
    assert results[0]["score"] == pytest.approx(0.9, abs=1e-3)
    assert results[0]["file"] == "USAGE.md"


def test_docs_index_answer_empty_index(tmp_path):
    """answer() on an empty index returns []."""
    import sys

    (tmp_path / "docs_meta.json").write_text("[]")

    fake_faiss_index = MagicMock()
    fake_faiss_index.ntotal = 0

    mock_faiss = MagicMock()
    mock_faiss.read_index.return_value = fake_faiss_index

    with patch.dict(sys.modules, {"faiss": mock_faiss}):
        idx = DocsIndex(tmp_path)

    results = idx.answer("anything", top_k=3)
    assert results == []
