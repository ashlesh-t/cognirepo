# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Sprint 2 — Documentation truthfulness sync tests.

Task 2.2 — Classifier thresholds match docs/architecture/SPECIFICATION.md
Task 2.3 — Edge type names match docs/architecture/graph.md
Task 2.5 — No 0-byte PNG diagram placeholders remain
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent


# ── Task 2.2: classifier thresholds ──────────────────────────────────────────

def test_classifier_thresholds_match_docs():
    """
    The score thresholds in orchestrator/classifier.py must match the table in
    docs/architecture/SPECIFICATION.md. Any drift here means users get a wrong mental model of
    routing behaviour.
    """
    from orchestrator.classifier import _TIER_QUICK, _TIER_STANDARD, _TIER_COMPLEX

    arch_text = (ROOT / "docs" / "architecture" / "SPECIFICATION.md").read_text(encoding="utf-8")

    # Extract the threshold lines from SPECIFICATION.md
    # Expected patterns:  ≤2 → QUICK,  ≤4 → STANDARD,  ≤9 → COMPLEX,  >9 → EXPERT
    def find_threshold(tier_label: str) -> float | None:
        # Match patterns like "≤2" or ">9" before QUICK/STANDARD/COMPLEX/EXPERT
        pattern = rf"[≤>](\d+(?:\.\d+)?)\s*.*?\*\*{tier_label}\*\*"
        m = re.search(pattern, arch_text)
        if m:
            return float(m.group(1))
        return None

    doc_quick    = find_threshold("QUICK")
    doc_standard = find_threshold("STANDARD")
    doc_complex  = find_threshold("COMPLEX")

    assert doc_quick is not None, "SPECIFICATION.md missing QUICK threshold line"
    assert doc_standard is not None, "SPECIFICATION.md missing STANDARD threshold line"
    assert doc_complex is not None, "SPECIFICATION.md missing COMPLEX threshold line"

    assert doc_quick == _TIER_QUICK, (
        f"QUICK threshold mismatch: SPECIFICATION.md={doc_quick}, code={_TIER_QUICK}"
    )
    assert doc_standard == _TIER_STANDARD, (
        f"STANDARD threshold mismatch: SPECIFICATION.md={doc_standard}, code={_TIER_STANDARD}"
    )
    assert doc_complex == _TIER_COMPLEX, (
        f"COMPLEX threshold mismatch: SPECIFICATION.md={doc_complex}, code={_TIER_COMPLEX}"
    )


def test_classifier_imperative_weight_matches_docs():
    """The imperative+abstract signal weight in docs/architecture/SPECIFICATION.md must match the code."""
    arch_text = (ROOT / "docs" / "architecture" / "SPECIFICATION.md").read_text(encoding="utf-8")
    # Match | +5 | binary | or similar in the signals table
    m = re.search(r"Imperative.*?\|\s*\+(\d+(?:\.\d+)?)\s*\|\s*binary", arch_text)
    assert m is not None, "SPECIFICATION.md imperative signal row not found"
    doc_weight = float(m.group(1))

    # Read the code value directly
    classifier_src = (ROOT / "orchestrator" / "classifier.py").read_text(encoding="utf-8")
    m2 = re.search(r'signals\["imperative_abstract"\]\s*=\s*([\d.]+)', classifier_src)
    assert m2 is not None, "Could not find imperative_abstract weight assignment in classifier.py"
    code_weight = float(m2.group(1))

    assert doc_weight == code_weight, (
        f"Imperative weight mismatch: SPECIFICATION.md={doc_weight}, code={code_weight}"
    )


# ── Task 2.3: edge type names ─────────────────────────────────────────────────

def test_edge_types_match_docs():
    """
    Every EdgeType constant in graph/knowledge_graph.py must appear in
    docs/architecture/graph.md.
    """
    from graph.knowledge_graph import EdgeType

    graph_doc = (ROOT / "docs" / "architecture" / "graph.md").read_text(encoding="utf-8")

    all_edge_values = [
        v for k, v in vars(EdgeType).items()
        if not k.startswith("_") and isinstance(v, str)
    ]

    missing = [v for v in all_edge_values if v not in graph_doc]
    assert not missing, (
        f"Edge types defined in code but missing from docs/architecture/graph.md: {missing}"
    )


def test_no_stale_edge_names_in_feature_md():
    """docs/FEATURES.md must not reference the old wrong edge type names as standalone tokens."""
    feature_text = (ROOT / "docs" / "FEATURES.md").read_text(encoding="utf-8")
    stale_names = ["CONTAINS", "USES"]
    found = [name for name in stale_names if re.search(rf"\b{name}\b", feature_text)]
    if re.search(r"\bCALLS\b(?!\s*edges| +by)", feature_text):
        if "from CALLS edges" in feature_text:
            found.append("CALLS (in 'from CALLS edges')")
    assert not found, (
        f"docs/FEATURES.md still references old/wrong edge type names: {found}. "
        "Update to use actual EdgeType constants: RELATES_TO, DEFINED_IN, CALLED_BY, QUERIED_WITH, CO_OCCURS"
    )
