#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
COGNIREPO-403/404 — output-side persona measurement harness.

NOT a shipped tool, NOT run in CI — dev script only. Measures the caveman persona's
claimed output-token reduction against docs/METRICS.md's input-side numbers, which this
repo has never had an output-side equivalent for (docs/METRICS.md measures context_pack
vs. raw reads; interface/tools/benchmark.py compares retrieval payloads, not generations).

This harness does NOT call any LLM API itself — it scores a fixed golden set of
{prompt, golden_facts, response_off, response_on} entries where BOTH responses were
captured from a real live agent session (a Claude Code session actually answering each
question about this repo, once verbosely and once under the caveman output_contract).
Re-running this script re-scores the same captured responses; it does not regenerate them.
To refresh the dataset with new live responses, edit
tests/fixtures/persona_bench_golden.json directly.

Usage:
    python scripts/persona_bench.py [--golden PATH] [--out PATH]

Ship gate (COGNIREPO-403 AC, COGNIREPO-404 description):
    median token reduction >= 40%  AND  |accuracy_off - accuracy_on| <= 2 percentage points
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_GOLDEN = REPO_ROOT / "tests" / "fixtures" / "persona_bench_golden.json"

_GATE_MIN_MEDIAN_REDUCTION_PCT = 40.0
_GATE_MAX_ACCURACY_DELTA_PP = 2.0


def _count_tokens(text: str) -> int:
    """Same encoder as context_pack.py:57 (cl100k_base) — falls back to char/4 if unavailable."""
    try:
        import tiktoken  # pylint: disable=import-outside-toplevel
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        return max(1, len(text) // 4)


def _accuracy(response: str, golden_facts: list[str]) -> float:
    """Fraction of golden_facts present as a case-insensitive substring of response."""
    if not golden_facts:
        return 1.0
    text_lower = response.lower()
    hits = sum(1 for fact in golden_facts if fact.lower() in text_lower)
    return hits / len(golden_facts)


def run(golden_path: Path) -> dict:
    entries = json.loads(golden_path.read_text(encoding="utf-8"))
    rows = []
    for entry in entries:
        off_text = entry["response_off"]
        on_text = entry["response_on"]
        off_tokens = _count_tokens(off_text)
        on_tokens = _count_tokens(on_text)
        reduction_pct = round((off_tokens - on_tokens) / off_tokens * 100, 1) if off_tokens else 0.0
        rows.append({
            "id": entry["id"],
            "prompt": entry["prompt"],
            "off_tokens": off_tokens,
            "on_tokens": on_tokens,
            "reduction_pct": reduction_pct,
            "accuracy_off": round(_accuracy(off_text, entry["golden_facts"]) * 100, 1),
            "accuracy_on": round(_accuracy(on_text, entry["golden_facts"]) * 100, 1),
        })

    median_reduction = round(statistics.median(r["reduction_pct"] for r in rows), 1)
    mean_accuracy_off = round(statistics.mean(r["accuracy_off"] for r in rows), 1)
    mean_accuracy_on = round(statistics.mean(r["accuracy_on"] for r in rows), 1)
    accuracy_delta_pp = round(mean_accuracy_off - mean_accuracy_on, 1)

    gate_passed = (
        median_reduction >= _GATE_MIN_MEDIAN_REDUCTION_PCT
        and abs(accuracy_delta_pp) <= _GATE_MAX_ACCURACY_DELTA_PP
    )

    return {
        "n": len(rows),
        "median_reduction_pct": median_reduction,
        "mean_accuracy_off_pct": mean_accuracy_off,
        "mean_accuracy_on_pct": mean_accuracy_on,
        "accuracy_delta_pp": accuracy_delta_pp,
        "gate": {
            "min_median_reduction_pct": _GATE_MIN_MEDIAN_REDUCTION_PCT,
            "max_accuracy_delta_pp": _GATE_MAX_ACCURACY_DELTA_PP,
            "passed": gate_passed,
        },
        "rows": rows,
    }


def print_report(report: dict) -> None:
    print(f"persona_bench — {report['n']} prompts\n")
    print("| id | off tok | on tok | reduction | acc off | acc on |")
    print("|---|---|---|---|---|---|")
    for r in report["rows"]:
        print(f"| {r['id']} | {r['off_tokens']} | {r['on_tokens']} | {r['reduction_pct']}% "
              f"| {r['accuracy_off']}% | {r['accuracy_on']}% |")
    print()
    print(f"Median reduction: **{report['median_reduction_pct']}%** "
          f"(gate: >= {report['gate']['min_median_reduction_pct']}%)")
    print(f"Accuracy delta (off - on): **{report['accuracy_delta_pp']}pp** "
          f"(gate: <= {report['gate']['max_accuracy_delta_pp']}pp)")
    verdict = "PASSED" if report["gate"]["passed"] else "MISSED"
    print(f"\nGate: **{verdict}**")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--out", type=Path, default=None, help="write JSON report to this path")
    args = parser.parse_args()

    report = run(args.golden)
    print_report(report)
    if args.out:
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nJSON report written: {args.out}")
    return 0 if report["gate"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
