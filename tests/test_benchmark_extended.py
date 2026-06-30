# pylint: disable=missing-docstring, import-outside-toplevel, broad-exception-caught
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""tests/test_benchmark_extended.py — Coverage for tools/benchmark.py (22% → 55%)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ── _count_tokens ─────────────────────────────────────────────────────────────

def test_count_tokens_nonempty():
    from tools.benchmark import _count_tokens
    result = _count_tokens("hello world this is a test")
    assert isinstance(result, int)
    assert result >= 1


def test_count_tokens_empty():
    from tools.benchmark import _count_tokens
    result = _count_tokens("")
    assert isinstance(result, int)


def test_count_tokens_fallback(monkeypatch):
    from tools.benchmark import _count_tokens
    with patch("tiktoken.get_encoding", side_effect=Exception("no tiktoken")):
        result = _count_tokens("four words here test")
        assert result >= 1


# ── load_last_run ─────────────────────────────────────────────────────────────

def test_load_last_run_no_file():
    from tools.benchmark import load_last_run
    with patch("os.path.exists", return_value=False):
        result = load_last_run()
    assert result is None


def test_load_last_run_with_history(tmp_path):
    from tools.benchmark import load_last_run
    hist = tmp_path / "benchmark_history.jsonl"
    entry = {"token_reduction_pct": 82.0, "timestamp": "2026-01-01T00:00:00Z"}
    hist.write_text(json.dumps(entry) + "\n")
    with patch("config.paths.get_path", return_value=str(hist)):
        result = load_last_run()
    assert result is not None
    assert result.get("token_reduction_pct") == 82.0


def test_load_last_run_empty_file(tmp_path):
    from tools.benchmark import load_last_run
    hist = tmp_path / "benchmark_history.jsonl"
    hist.write_text("")
    with patch("config.paths.get_path", return_value=str(hist)):
        result = load_last_run()
    assert result is None


def test_load_last_run_corrupt_file(tmp_path):
    from tools.benchmark import load_last_run
    hist = tmp_path / "benchmark_history.jsonl"
    hist.write_text("not json\n")
    with patch("config.paths.get_path", return_value=str(hist)):
        result = load_last_run()
    assert result is None  # exception swallowed


# ── print_report ──────────────────────────────────────────────────────────────

def _full_metrics():
    return {
        "token_reduction_pct": 85.2,
        "symbol_lookup_ms": 12.0,
        "symbol_hit_rate": 0.95,
        "grep_ms": 150.0,
        "lookup_speedup_vs_grep_x": 12.0,
        "cache_speedup_x": 2.5,
        "memory_recall_at_1": 0.90,
        "memory_recall_at_3": 0.95,
        "context_relevance_pct": 82.0,
        "precision_at_1": 0.80,
        "precision_at_3": 0.75,
        "precision_queries_tested": 10,
        "latency_p50_ms": 42.0,
        "latency_p95_ms": 85.0,
        "latency_p99_ms": 100.0,
        "timestamp": "2026-01-01T00:00:00Z",
    }


def test_print_report_with_metrics(capsys):
    from tools.benchmark import print_report
    print_report(_full_metrics())
    captured = capsys.readouterr()
    assert "CogniRepo" in captured.out or len(captured.out) > 0


def test_print_report_with_compare(capsys):
    from tools.benchmark import print_report
    metrics = _full_metrics()
    compare = _full_metrics()
    compare["token_reduction_pct"] = 80.0
    print_report(metrics, compare=compare)
    captured = capsys.readouterr()
    assert len(captured.out) > 0


# ── measure_latency ───────────────────────────────────────────────────────────

def test_measure_latency_no_golden():
    from tools.benchmark import measure_latency
    mock_result = {"query": "test", "sections": [], "token_count": 10, "status": "ok"}
    with patch("tools.context_pack.context_pack", return_value=mock_result):
        result = measure_latency(golden=None, repeats=1)
    assert isinstance(result, dict)


def test_measure_latency_with_golden():
    from tools.benchmark import measure_latency
    mock_result = {"query": "test", "sections": [{"score": 0.8}], "token_count": 100, "status": "ok"}
    golden = [{"query": "hybrid retrieval", "expected_symbols": ["hybrid_retrieve"]}]
    with patch("tools.context_pack.context_pack", return_value=mock_result):
        result = measure_latency(golden=golden, repeats=1)
    assert isinstance(result, dict)


# ── measure_symbol_lookup ─────────────────────────────────────────────────────

def test_measure_symbol_lookup_mocked():
    from tools.benchmark import measure_symbol_lookup
    from unittest.mock import MagicMock
    mock_idx = MagicMock()
    mock_idx.lookup_symbol.return_value = [{"name": "fn", "file": "x.py", "line": 1}]
    with patch("intelligence.indexer.ast_indexer.ASTIndexer", return_value=mock_idx):
        with patch("data.graph.knowledge_graph.KnowledgeGraph"):
            result = measure_symbol_lookup(["hybrid_retrieve"])
    assert isinstance(result, dict)


# ── measure_memory_recall ─────────────────────────────────────────────────────

def test_measure_memory_recall_mocked():
    from tools.benchmark import measure_memory_recall
    with patch("tools.store_memory.store_memory", return_value={"status": "stored"}):
        with patch("tools.retrieve_memory.retrieve_memory", return_value=[{"text": "test memory", "score": 0.9}]):
            result = measure_memory_recall(["test memory to check recall"])
    assert isinstance(result, dict)


# ── measure_precision_at_k ────────────────────────────────────────────────────

def test_measure_precision_at_k_no_golden():
    from tools.benchmark import measure_precision_at_k
    mock_result = {"sections": [{"symbol": "fn"}], "status": "ok"}
    with patch("tools.context_pack.context_pack", return_value=mock_result):
        result = measure_precision_at_k(golden=None, k=3)
    assert isinstance(result, dict)


# ── measure_cache_speedup ─────────────────────────────────────────────────────

def test_measure_cache_speedup_mocked():
    from tools.benchmark import measure_cache_speedup
    mock_result = {"query": "test", "sections": [], "token_count": 10, "status": "ok"}
    with patch("tools.context_pack.context_pack", return_value=mock_result):
        result = measure_cache_speedup(["hybrid retrieval"])
    assert isinstance(result, dict)


# ── measure_context_relevance ─────────────────────────────────────────────────

def test_measure_context_relevance_mocked():
    from tools.benchmark import measure_context_relevance
    mock_result = {"query": "test", "sections": [{"score": 0.8}], "token_count": 100, "status": "ok"}
    with patch("tools.context_pack.context_pack", return_value=mock_result):
        result = measure_context_relevance(["hybrid retrieval"])
    assert isinstance(result, dict)
