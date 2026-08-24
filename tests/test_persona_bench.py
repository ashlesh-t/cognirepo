# pylint: disable=missing-docstring
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_persona_bench.py — scripts/persona_bench.py (COGNIREPO-404) unit tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import persona_bench  # noqa: E402  pylint: disable=wrong-import-position


def test_accuracy_full_match():
    assert persona_bench._accuracy("hybrid.py:424, log(1+hit_count)", ["hybrid.py:424", "log", "hit_count"]) == 1.0


def test_accuracy_partial_match():
    score = persona_bench._accuracy("hybrid.py:424", ["hybrid.py:424", "hit_count", "log"])
    assert 0.3 < score < 0.4


def test_accuracy_case_insensitive():
    assert persona_bench._accuracy("HYBRID.PY:424", ["hybrid.py:424"]) == 1.0


def test_accuracy_no_golden_facts_returns_one():
    assert persona_bench._accuracy("anything", []) == 1.0


def test_count_tokens_nonzero_for_nonempty_text():
    assert persona_bench._count_tokens("hello world") > 0


def test_count_tokens_scales_with_length():
    short = persona_bench._count_tokens("short text")
    long_text = persona_bench._count_tokens("a much longer piece of text with many more words in it")
    assert long_text > short


def test_run_end_to_end_on_real_golden_set(tmp_path):
    """AC1: harness runs end-to-end and emits a report."""
    report = persona_bench.run(persona_bench.DEFAULT_GOLDEN)
    assert report["n"] == 20
    assert "median_reduction_pct" in report
    assert "gate" in report
    assert isinstance(report["gate"]["passed"], bool)
    assert len(report["rows"]) == 20


def test_run_on_synthetic_fixture(tmp_path):
    fixture = [
        {
            "id": "t1",
            "prompt": "test",
            "golden_facts": ["fact1", "fact2"],
            "response_off": "this is a long response containing fact1 and also fact2 in it somewhere",
            "response_on": "fact1 fact2",
        }
    ]
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    report = persona_bench.run(path)
    assert report["n"] == 1
    assert report["rows"][0]["accuracy_off"] == 100.0
    assert report["rows"][0]["accuracy_on"] == 100.0
    assert report["rows"][0]["on_tokens"] < report["rows"][0]["off_tokens"]


def test_gate_fails_when_accuracy_drops_on_persona(tmp_path):
    fixture = [
        {
            "id": "t1", "prompt": "test", "golden_facts": ["fact1", "fact2"],
            "response_off": "fact1 and fact2 are both explained here in detail with context",
            "response_on": "short answer with no facts",
        }
    ]
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    report = persona_bench.run(path)
    assert report["gate"]["passed"] is False
    assert report["accuracy_delta_pp"] > persona_bench._GATE_MAX_ACCURACY_DELTA_PP
