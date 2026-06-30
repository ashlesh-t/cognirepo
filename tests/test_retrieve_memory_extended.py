# pylint: disable=missing-docstring, import-outside-toplevel, broad-exception-caught
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""tests/test_retrieve_memory_extended.py — Coverage for tools/retrieve_memory.py (38% → 80%)."""
from __future__ import annotations

from unittest.mock import patch

import pytest


MOCK_AST_HIT = {
    "text": "FUNCTION hybrid_retrieve in retrieval/hybrid.py:42 — core retrieval function",
    "source": "ast",
    "final_score": 0.75,
    "importance": 0.75,
}

MOCK_DOC_HIT = {
    "text": "CogniRepo — persistent memory layer for AI agents — stores semantic context",
    "source": "semantic",
    "final_score": 0.55,
    "importance": 0.55,
}


# ── retrieve_memory flat list ─────────────────────────────────────────────────

def test_retrieve_memory_returns_list():
    from interface.tools.retrieve_memory import retrieve_memory
    with patch("interface.tools.retrieve_memory.hybrid_retrieve", return_value=[MOCK_AST_HIT]):
        result = retrieve_memory("hybrid retrieval")
    assert isinstance(result, list)


def test_retrieve_memory_empty():
    from interface.tools.retrieve_memory import retrieve_memory
    with patch("interface.tools.retrieve_memory.hybrid_retrieve", return_value=[]):
        result = retrieve_memory("missing query")
    assert result == []


def test_retrieve_memory_query_too_long():
    from interface.tools.retrieve_memory import retrieve_memory
    with pytest.raises(ValueError, match="Query too long"):
        retrieve_memory("x" * 100_001)


def test_retrieve_memory_min_score_filter():
    from interface.tools.retrieve_memory import retrieve_memory
    low_score = {**MOCK_AST_HIT, "final_score": 0.1}
    with patch("interface.tools.retrieve_memory.hybrid_retrieve", return_value=[low_score]):
        result = retrieve_memory("query", min_score=0.0)
    assert isinstance(result, list)


# ── _dedup ────────────────────────────────────────────────────────────────────

def test_dedup_removes_duplicates():
    from interface.tools.retrieve_memory import _dedup
    entry = {
        "text": "FUNCTION foo in src/foo.py:10 — does something",
        "source": "ast",
        "final_score": 0.9,
    }
    results = [entry, entry.copy()]
    deduped = _dedup(results)
    assert len(deduped) == 1


def test_dedup_keeps_distinct_entries():
    from interface.tools.retrieve_memory import _dedup
    e1 = {"text": "FUNCTION foo in src/a.py:10 — foo", "source": "ast", "final_score": 0.9}
    e2 = {"text": "FUNCTION bar in src/b.py:20 — bar", "source": "ast", "final_score": 0.8}
    deduped = _dedup([e1, e2])
    assert len(deduped) == 2


def test_dedup_plain_text_key():
    from interface.tools.retrieve_memory import _dedup
    e1 = {"text": "plain memory text", "source": "semantic", "final_score": 0.5}
    e2 = {"text": "plain memory text", "source": "semantic", "final_score": 0.5}
    deduped = _dedup([e1, e2])
    assert len(deduped) == 1


# ── structured=True ───────────────────────────────────────────────────────────

def test_retrieve_memory_structured_shape():
    from interface.tools.retrieve_memory import retrieve_memory
    with patch("interface.tools.retrieve_memory.hybrid_retrieve", return_value=[MOCK_AST_HIT, MOCK_DOC_HIT]):
        result = retrieve_memory("retrieval", structured=True)
    assert isinstance(result, dict)
    assert "code_hits" in result
    assert "doc_hits" in result
    assert "confidence" in result


def test_retrieve_memory_structured_confidence_high():
    from interface.tools.retrieve_memory import retrieve_memory
    high = {**MOCK_AST_HIT, "final_score": 0.85}
    with patch("interface.tools.retrieve_memory.hybrid_retrieve", return_value=[high]):
        result = retrieve_memory("retrieval", structured=True)
    assert result["confidence"] == "high"


def test_retrieve_memory_structured_confidence_medium():
    from interface.tools.retrieve_memory import retrieve_memory
    medium = {**MOCK_AST_HIT, "final_score": 0.45}
    with patch("interface.tools.retrieve_memory.hybrid_retrieve", return_value=[medium]):
        result = retrieve_memory("retrieval", structured=True)
    assert result["confidence"] == "medium"


def test_retrieve_memory_structured_confidence_low():
    from interface.tools.retrieve_memory import retrieve_memory
    low = {**MOCK_AST_HIT, "final_score": 0.1}
    with patch("interface.tools.retrieve_memory.hybrid_retrieve", return_value=[low]):
        result = retrieve_memory("retrieval", structured=True)
    assert result["confidence"] == "low"


def test_retrieve_memory_structured_code_hit_extraction():
    from interface.tools.retrieve_memory import retrieve_memory
    with patch("interface.tools.retrieve_memory.hybrid_retrieve", return_value=[MOCK_AST_HIT]):
        result = retrieve_memory("retrieval", structured=True)
    code_hits = result["code_hits"]
    assert len(code_hits) >= 1
    hit = code_hits[0]
    assert "symbol" in hit
    assert "file" in hit
    assert "line" in hit
    assert "score" in hit


def test_retrieve_memory_structured_doc_hit():
    from interface.tools.retrieve_memory import retrieve_memory
    with patch("interface.tools.retrieve_memory.hybrid_retrieve", return_value=[MOCK_DOC_HIT]):
        result = retrieve_memory("cognirepo", structured=True)
    doc_hits = result["doc_hits"]
    assert len(doc_hits) >= 1
    assert "source" in doc_hits[0]
    assert "section" in doc_hits[0]


def test_retrieve_memory_structured_empty():
    from interface.tools.retrieve_memory import retrieve_memory
    with patch("interface.tools.retrieve_memory.hybrid_retrieve", return_value=[]):
        result = retrieve_memory("nothing", structured=True)
    assert result["code_hits"] == []
    assert result["doc_hits"] == []
    assert result["confidence"] == "low"


# ── _structure_results edge cases ────────────────────────────────────────────

def test_structure_results_no_in_separator():
    from interface.tools.retrieve_memory import _structure_results
    hit = {"text": "plain text no separator", "source": "semantic", "final_score": 0.5}
    result = _structure_results([hit])
    assert len(result["doc_hits"]) == 1


def test_structure_results_with_dash_section():
    from interface.tools.retrieve_memory import _structure_results
    hit = {
        "text": "Memory about auth — JWT tokens are stored in keychain",
        "source": "semantic",
        "final_score": 0.6,
    }
    result = _structure_results([hit])
    assert "JWT tokens" in result["doc_hits"][0]["section"]
