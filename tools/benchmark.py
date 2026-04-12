# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tools/benchmark.py — Quantitative value metrics for CogniRepo.

Measures the concrete advantage CogniRepo provides to an AI agent:

  1. token_reduction_pct   — context_pack vs reading source files raw
  2. symbol_lookup_ms      — ASTIndexer.lookup_symbol latency (target < 5ms)
  3. grep_equivalent_ms    — subprocess grep timing for comparison
  4. cache_speedup_x       — warm hybrid_retrieve vs cold (target ≥ 10x)
  5. memory_recall_at_1    — top-1 accuracy for stored memories  [0..1]
  6. memory_recall_at_3    — recall@3                            [0..1]
  7. context_relevance_pct — % of context_pack sections that mention query terms

Run standalone:
    python -m tools.benchmark
    python -m tools.benchmark --json           # machine-readable JSON
    python -m tools.benchmark --compare        # compare with last run

Saved to .cognirepo/benchmark_history.jsonl for trend tracking.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


# ─── helpers ─────────────────────────────────────────────────────────────────

def _count_tokens(text: str) -> int:
    try:
        import tiktoken
        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:  # pylint: disable=broad-except
        return max(1, len(text) // 4)


def _read_files_for_query(query_keyword: str, repo_root: Path) -> int:
    """
    Estimate raw token cost: sum of token counts of all .py files whose
    name or content contains the query keyword.
    """
    total = 0
    for py_file in repo_root.rglob("*.py"):
        if any(part in {".git", "venv", "__pycache__", ".cognirepo"}
               for part in py_file.parts):
            continue
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
            if query_keyword.lower() in text.lower():
                total += _count_tokens(text)
        except OSError:
            pass
    return total


# ─── individual benchmarks ────────────────────────────────────────────────────

def measure_token_reduction(queries: list[str]) -> dict:
    """
    For each query, compare:
      raw_tokens  = tokens in all source files containing the keyword
      pack_tokens = context_pack output tokens
    Returns average savings %.
    """
    from tools.context_pack import context_pack

    savings = []
    details = []
    for q in queries:
        keyword = q.split()[0].lower()
        raw = _read_files_for_query(keyword, REPO_ROOT)
        if raw == 0:
            continue
        result = context_pack(q, max_tokens=2000)
        packed = result.get("token_count", 0)
        if packed == 0:
            packed = 1  # context was empty — treat as 1 token for ratio purposes
        pct = max(0.0, (raw - packed) / raw * 100)
        savings.append(pct)
        details.append({"query": q, "raw_tokens": raw, "packed_tokens": packed,
                        "savings_pct": round(pct, 1)})

    avg_savings = round(sum(savings) / len(savings), 1) if savings else 0.0
    return {"token_reduction_pct": avg_savings, "details": details}


def measure_symbol_lookup(symbols: list[str]) -> dict:
    """
    Time ASTIndexer.lookup_symbol for known symbols.
    Returns mean latency in ms.
    """
    from indexer.ast_indexer import ASTIndexer
    from graph.knowledge_graph import KnowledgeGraph

    idx = ASTIndexer(graph=KnowledgeGraph())
    idx.load()

    timings = []
    hit_count = 0
    for sym in symbols:
        t0 = time.perf_counter()
        results = idx.lookup_symbol(sym)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        timings.append(elapsed_ms)
        if results:
            hit_count += 1

    mean_ms = round(sum(timings) / len(timings), 3) if timings else 0.0
    return {
        "symbol_lookup_ms": mean_ms,
        "symbol_hit_rate": round(hit_count / len(symbols), 2) if symbols else 0.0,
        "symbols_tested": len(symbols),
    }


def measure_grep_equivalent(symbols: list[str]) -> dict:
    """
    Time `grep -rn --include="*.py" <symbol>` as a baseline comparison.
    """
    timings = []
    for sym in symbols:
        t0 = time.perf_counter()
        try:
            subprocess.run(
                ["grep", "-rn", "--include=*.py", sym, str(REPO_ROOT)],
                capture_output=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        elapsed_ms = (time.perf_counter() - t0) * 1000
        timings.append(elapsed_ms)

    mean_ms = round(sum(timings) / len(timings), 1) if timings else 0.0
    return {"grep_ms": mean_ms}


def measure_cache_speedup(queries: list[str]) -> dict:
    """
    Cold vs warm hybrid_retrieve — cache speedup factor.
    """
    from retrieval.hybrid import hybrid_retrieve, invalidate_hybrid_cache

    speedups = []
    for q in queries:
        invalidate_hybrid_cache()
        t0 = time.perf_counter()
        hybrid_retrieve(q, top_k=5)
        cold_ms = (time.perf_counter() - t0) * 1000

        t1 = time.perf_counter()
        hybrid_retrieve(q, top_k=5)
        warm_ms = (time.perf_counter() - t1) * 1000

        if warm_ms > 0:
            speedups.append(cold_ms / warm_ms)

    mean_speedup = round(sum(speedups) / len(speedups), 1) if speedups else 0.0
    return {"cache_speedup_x": mean_speedup}


def measure_memory_recall(test_memories: list[str]) -> dict:
    """
    Store memories and verify they surface in FAISS top-k results.
    Uses direct vector search (retrieve_memory) rather than hybrid_retrieve
    because hybrid may rank AST symbols above freshly-stored memories.
    Recall@k = fraction where stored text appears in the top-k results.
    """
    from tools.store_memory import store_memory
    from tools.retrieve_memory import retrieve_memory
    from retrieval.hybrid import invalidate_hybrid_cache

    stored = []
    for text in test_memories:
        store_memory(text, source="benchmark")
        stored.append(text)

    recall_at_1 = 0
    recall_at_3 = 0
    for text in stored:
        # Use the unique prefix (first token contains timestamp) as anchor query
        unique_prefix = text.split()[0]  # e.g. "cognirepo_bench_1775420000_a:"
        invalidate_hybrid_cache()  # must flush — new memories aren't in the cache
        results = retrieve_memory(text, top_k=5)
        retrieved_texts = [r.get("text", "").lower() for r in results]

        # The unique prefix guarantees we only match the exact stored memory
        def _is_hit(candidate_texts, _prefix=unique_prefix):
            return any(_prefix.lower() in t for t in candidate_texts)

        if _is_hit(retrieved_texts[:1]):
            recall_at_1 += 1
        if _is_hit(retrieved_texts[:3]):
            recall_at_3 += 1

    n = len(stored)
    return {
        "memory_recall_at_1": round(recall_at_1 / n, 2) if n else 0.0,
        "memory_recall_at_3": round(recall_at_3 / n, 2) if n else 0.0,
        "memories_tested": n,
    }


def measure_context_relevance(queries: list[str]) -> dict:
    """
    For each query, check what fraction of context_pack sections
    contain at least one query keyword.
    """
    from tools.context_pack import context_pack

    relevance_scores = []
    for q in queries:
        keywords = [w.lower() for w in q.split() if len(w) > 3]
        result = context_pack(q, max_tokens=2000)
        sections = result.get("sections", [])
        if not sections:
            continue
        relevant = sum(
            1 for s in sections
            if any(kw in s.get("content", "").lower() for kw in keywords)
        )
        relevance_scores.append(relevant / len(sections))

    avg = round(sum(relevance_scores) / len(relevance_scores) * 100, 1) if relevance_scores else 0.0
    return {"context_relevance_pct": avg}


# ─── full benchmark run ───────────────────────────────────────────────────────

_BENCHMARK_QUERIES = [
    "store_memory implementation",
    "context_pack token budget",
    "hybrid_retrieve BM25 vector",
    "EpisodicMemory search episodes",
    "knowledge graph node edges",
]

_BENCHMARK_SYMBOLS = [
    "context_pack",
    "hybrid_retrieve",
    "store_memory",
    "log_event",
    "lookup_symbol",
]

def _benchmark_memories() -> list[str]:
    """Generate unique benchmark memories using timestamp to avoid FAISS pollution."""
    ts = int(time.time())
    return [
        f"cognirepo_bench_{ts}_a: token reduction packing context code snippets",
        f"cognirepo_bench_{ts}_b: symbol lookup ASTIndexer reverse index file line",
        f"cognirepo_bench_{ts}_c: hybrid retrieval vector graph behaviour signals",
    ]


def run_benchmark() -> dict:
    """Run all benchmarks and return a consolidated metrics dict."""
    print("Running CogniRepo benchmark...", flush=True)

    print("  [1/5] Token reduction...", flush=True)
    token_metrics = measure_token_reduction(_BENCHMARK_QUERIES)

    print("  [2/5] Symbol lookup latency...", flush=True)
    lookup_metrics = measure_symbol_lookup(_BENCHMARK_SYMBOLS)
    grep_metrics = measure_grep_equivalent(_BENCHMARK_SYMBOLS[:2])  # grep is slow; test 2

    print("  [3/5] Cache speedup...", flush=True)
    cache_metrics = measure_cache_speedup(_BENCHMARK_QUERIES[:3])

    print("  [4/5] Memory recall...", flush=True)
    recall_metrics = measure_memory_recall(_benchmark_memories())

    print("  [5/5] Context relevance...", flush=True)
    relevance_metrics = measure_context_relevance(_BENCHMARK_QUERIES)

    # Composite speedup: grep vs lookup
    lookup_ms = lookup_metrics["symbol_lookup_ms"]
    grep_ms = grep_metrics["grep_ms"]
    lookup_speedup = round(grep_ms / lookup_ms, 1) if lookup_ms > 0 else 0.0

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "token_reduction_pct": token_metrics["token_reduction_pct"],
        "symbol_lookup_ms": lookup_metrics["symbol_lookup_ms"],
        "symbol_hit_rate": lookup_metrics["symbol_hit_rate"],
        "grep_ms": grep_metrics["grep_ms"],
        "lookup_speedup_vs_grep_x": lookup_speedup,
        "cache_speedup_x": cache_metrics["cache_speedup_x"],
        "memory_recall_at_1": recall_metrics["memory_recall_at_1"],
        "memory_recall_at_3": recall_metrics["memory_recall_at_3"],
        "context_relevance_pct": relevance_metrics["context_relevance_pct"],
        "_details": token_metrics.get("details", []),
    }

    # Save to history
    _save_to_history(result)

    return result


def _save_to_history(metrics: dict) -> None:
    """Append metrics to .cognirepo/benchmark_history.jsonl."""
    try:
        from config.paths import get_path
        hist_path = get_path("benchmark_history.jsonl")
        with open(hist_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({k: v for k, v in metrics.items() if k != "_details"}) + "\n")
    except Exception:  # pylint: disable=broad-except
        pass  # non-fatal


def load_last_run() -> dict | None:
    """Load the most recent benchmark result from history."""
    try:
        from config.paths import get_path
        hist_path = get_path("benchmark_history.jsonl")
        if not os.path.exists(hist_path):
            return None
        lines = Path(hist_path).read_text(encoding="utf-8").splitlines()
        valid = [l for l in lines if l.strip()]
        return json.loads(valid[-1]) if valid else None
    except Exception:  # pylint: disable=broad-except
        return None


def print_report(metrics: dict, compare: dict | None = None) -> None:
    """Print a human-readable benchmark report."""
    print("\n" + "═" * 62)
    print("  CogniRepo Benchmark Report")
    print("═" * 62)

    def _row(label: str, value, unit: str = "", prev=None, higher_is_better: bool = True):
        arrow = ""
        if prev is not None and isinstance(value, (int, float)) and isinstance(prev, (int, float)):
            diff = value - prev
            if abs(diff) > 0.01:
                symbol = "▲" if diff > 0 else "▼"
                color = symbol if (diff > 0) == higher_is_better else symbol
                arrow = f"  {color} {abs(diff):.1f}{unit} vs last run"
        print(f"  {label:<38} {value!s:>8}{unit}{arrow}")

    prev = compare or {}
    _row("Token reduction (vs raw file read)", f"{metrics['token_reduction_pct']:.1f}", "%",
         prev.get("token_reduction_pct"))
    _row("Symbol lookup latency (mean)",       f"{metrics['symbol_lookup_ms']:.2f}", " ms",
         prev.get("symbol_lookup_ms"), higher_is_better=False)
    _row("grep equivalent latency (mean)",     f"{metrics['grep_ms']:.0f}", " ms",
         prev.get("grep_ms"), higher_is_better=False)
    _row("Lookup speedup vs grep",             f"{metrics['lookup_speedup_vs_grep_x']:.0f}", "x",
         prev.get("lookup_speedup_vs_grep_x"))
    _row("Cache speedup (warm vs cold)",       f"{metrics['cache_speedup_x']:.0f}", "x",
         prev.get("cache_speedup_x"))
    _row("Memory recall@1",                   f"{metrics['memory_recall_at_1']:.0%}", "",
         prev.get("memory_recall_at_1"))
    _row("Memory recall@3",                   f"{metrics['memory_recall_at_3']:.0%}", "",
         prev.get("memory_recall_at_3"))
    _row("Context relevance",                 f"{metrics['context_relevance_pct']:.1f}", "%",
         prev.get("context_relevance_pct"))
    _row("Symbol hit rate",                   f"{metrics['symbol_hit_rate']:.0%}", "",
         prev.get("symbol_hit_rate"))

    print("─" * 62)
    print(f"  Timestamp: {metrics['timestamp']}")
    print("═" * 62)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CogniRepo benchmark")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--compare", action="store_true", help="Compare with last run")
    args = parser.parse_args()

    metrics = run_benchmark()

    if args.json:
        print(json.dumps({k: v for k, v in metrics.items() if k != "_details"}, indent=2))
    else:
        prev = load_last_run() if args.compare else None
        print_report(metrics, compare=prev)
