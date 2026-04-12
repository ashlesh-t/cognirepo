# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Sprint 2 — Documentation truthfulness sync tests.

Task 2.2 — Classifier thresholds match ARCHITECTURE.md
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
    ARCHITECTURE.md. Any drift here means users get a wrong mental model of
    routing behaviour.
    """
    from orchestrator.classifier import _TIER_QUICK, _TIER_STANDARD, _TIER_COMPLEX

    arch_text = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")

    # Extract the threshold lines from ARCHITECTURE.md
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

    assert doc_quick is not None, "ARCHITECTURE.md missing QUICK threshold line"
    assert doc_standard is not None, "ARCHITECTURE.md missing STANDARD threshold line"
    assert doc_complex is not None, "ARCHITECTURE.md missing COMPLEX threshold line"

    assert doc_quick == _TIER_QUICK, (
        f"QUICK threshold mismatch: ARCHITECTURE.md={doc_quick}, code={_TIER_QUICK}"
    )
    assert doc_standard == _TIER_STANDARD, (
        f"STANDARD threshold mismatch: ARCHITECTURE.md={doc_standard}, code={_TIER_STANDARD}"
    )
    assert doc_complex == _TIER_COMPLEX, (
        f"COMPLEX threshold mismatch: ARCHITECTURE.md={doc_complex}, code={_TIER_COMPLEX}"
    )


def test_classifier_imperative_weight_matches_docs():
    """The imperative+abstract signal weight in ARCHITECTURE.md must match the code."""
    arch_text = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    # Match | +5 | binary | or similar in the signals table
    m = re.search(r"Imperative.*?\|\s*\+(\d+(?:\.\d+)?)\s*\|\s*binary", arch_text)
    assert m is not None, "ARCHITECTURE.md imperative signal row not found"
    doc_weight = float(m.group(1))

    # Read the code value directly
    classifier_src = (ROOT / "orchestrator" / "classifier.py").read_text(encoding="utf-8")
    m2 = re.search(r'signals\["imperative_abstract"\]\s*=\s*([\d.]+)', classifier_src)
    assert m2 is not None, "Could not find imperative_abstract weight assignment in classifier.py"
    code_weight = float(m2.group(1))

    assert doc_weight == code_weight, (
        f"Imperative weight mismatch: ARCHITECTURE.md={doc_weight}, code={code_weight}"
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
    """FEATURE.md must not reference the old wrong edge type names as standalone tokens."""
    feature_text = (ROOT / "FEATURE.md").read_text(encoding="utf-8")
    # Check for old edge names as whole words (not as substrings of CALLED_BY etc.)
    stale_names = ["CONTAINS", "USES"]
    found = [name for name in stale_names if re.search(rf"\b{name}\b", feature_text)]
    # "CALLS" as standalone (not part of "CALLED_BY" or "who_calls")
    if re.search(r"\bCALLS\b(?!\s*edges| +by)", feature_text):
        # Allow "CALLED_BY" and "CALLS edges" — flag bare "CALLS" as an edge type
        # Check specifically for "from CALLS edges" pattern (old wrong docs)
        if "from CALLS edges" in feature_text:
            found.append("CALLS (in 'from CALLS edges')")
    assert not found, (
        f"FEATURE.md still references old/wrong edge type names: {found}. "
        "Update to use actual EdgeType constants: RELATES_TO, DEFINED_IN, CALLED_BY, QUERIED_WITH, CO_OCCURS"
    )


# ── Task 2.5: no 0-byte PNG diagrams ─────────────────────────────────────────

def test_no_zero_byte_pngs():
    """All PNG files under docs/ must be non-zero bytes (no placeholder stubs)."""
    diagram_dir = ROOT / "docs" / "architecture" / "diagrams"
    pngs = list(diagram_dir.glob("*.png"))
    assert pngs, f"No PNG files found under {diagram_dir}"

    zero_byte = [p for p in pngs if p.stat().st_size == 0]
    assert not zero_byte, (
        "0-byte PNG placeholder(s) found — run scripts/build_diagrams.sh to regenerate: "
        + ", ".join(str(p.relative_to(ROOT)) for p in zero_byte)
    )


def test_pngs_are_valid_png_format():
    """PNG files must start with the PNG magic bytes (not empty or garbage)."""
    diagram_dir = ROOT / "docs" / "architecture" / "diagrams"
    PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

    for png in diagram_dir.glob("*.png"):
        with open(png, "rb") as f:
            header = f.read(8)
        assert header == PNG_MAGIC, (
            f"{png.name} is not a valid PNG file (bad magic bytes). "
            "Regenerate with scripts/build_diagrams.sh"
        )


# ── Task 2.1: no stale 4-signal references ───────────────────────────────────

def test_no_four_signal_in_docs():
    """
    The term '4-signal' must not appear in user-facing documentation.
    SPRINT.md and CHANGELOG.md are excluded (historical / task-tracking context).
    docs/architecture/retrieval.md is excluded (it mentions '4-signal' only to
    explain why the label was incorrect).
    """
    # Historical / meta files — allowed to reference the old label for context
    excluded = {"SPRINT.md", "CHANGELOG.md"}
    excluded_paths = {str((ROOT / "docs" / "architecture" / "retrieval.md").resolve())}

    doc_files = list(ROOT.glob("*.md")) + list((ROOT / "docs").rglob("*.md"))
    violations = []
    for doc in doc_files:
        if doc.name in excluded:
            continue
        if str(doc.resolve()) in excluded_paths:
            continue
        text = doc.read_text(encoding="utf-8", errors="replace")
        if "4-signal" in text or "four-signal" in text.lower():
            violations.append(str(doc.relative_to(ROOT)))
    assert not violations, (
        f"Stale '4-signal' reference found in docs — update to '3-signal': {violations}"
    )


# ── Sprint 4.3: new tier names in docs ───────────────────────────────────────

_TIER_HISTORICAL = {"SPRINT.md", "CHANGELOG.md", "EXECUTION_PLAN_v3.md"}
_OLD_TIER_TOKENS = re.compile(r"(?<![A-Z_])(?:FAST|BALANCED|DEEP)(?![A-Z_])")


def test_new_tier_names_in_architecture_md():
    """ARCHITECTURE.md must use the new tier names: STANDARD, COMPLEX, EXPERT."""
    arch_text = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    for name in ("STANDARD", "COMPLEX", "EXPERT"):
        assert name in arch_text, f"ARCHITECTURE.md missing new tier name '{name}'"


def test_no_old_tier_names_in_user_docs():
    """
    FAST / BALANCED / DEEP must not appear as standalone tier tokens in user-facing docs.
    Historical / meta files (CHANGELOG, SPRINT, execution plan) are excluded.
    """
    doc_files = list(ROOT.glob("*.md")) + list((ROOT / "docs").rglob("*.md"))
    violations = []
    for doc in doc_files:
        if doc.name in _TIER_HISTORICAL:
            continue
        text = doc.read_text(encoding="utf-8", errors="replace")
        for m in _OLD_TIER_TOKENS.finditer(text):
            line_no = text[: m.start()].count("\n") + 1
            violations.append(f"{doc.relative_to(ROOT)}:{line_no}: '{m.group()}'")
    assert not violations, (
        "Old tier names (FAST/BALANCED/DEEP) found in user-facing docs — "
        "rename to STANDARD/COMPLEX/EXPERT:\n  " + "\n  ".join(violations)
    )


def test_cli_config_path_in_cli_md():
    """docs/CLI.md must document the cli_config.toml path."""
    cli_md = ROOT / "docs" / "CLI.md"
    if not cli_md.exists():
        import pytest
        pytest.skip("docs/CLI.md not yet created")
    text = cli_md.read_text(encoding="utf-8")
    assert "cli_config.toml" in text, "docs/CLI.md must mention cli_config.toml path"
    assert "~/.cognirepo" in text, "docs/CLI.md must document the ~/.cognirepo/ config location"


def test_metrics_endpoint_mentioned():
    """
    At least one doc file must mention /metrics (Prometheus scrape endpoint).
    """
    doc_files = list(ROOT.glob("*.md")) + list((ROOT / "docs").rglob("*.md"))
    found = any(
        "/metrics" in doc.read_text(encoding="utf-8", errors="replace")
        for doc in doc_files
    )
    assert found, (
        "No doc file mentions '/metrics'. Add a Prometheus /metrics reference "
        "to USAGE.md or docs/CLI.md."
    )
