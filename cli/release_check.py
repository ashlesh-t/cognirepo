# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Sprint 4.3 — Release readiness checks.

``run_release_checks()`` scans all user-facing docs for:
  - Legacy version references  (v0.x)
  - Old tier names             (FAST / BALANCED / DEEP as standalone tokens)

Returns a list of violation strings.  Empty list → release is clean.
"""

from __future__ import annotations

import re
from pathlib import Path

# Files that are allowed to mention v0.x or old tier names (historical context)
_ALLOWED_FILES = {
    "CHANGELOG.md",
    "SPRINT.md",
    "EXECUTION_PLAN_v3.md",
}

# Old tier names that should no longer appear in user-facing docs
_OLD_TIER_NAMES = ["FAST", "BALANCED", "DEEP"]

# Regex: standalone v0.x version reference (e.g. v0.5.0, v0.2, v0.x)
_V0_PATTERN = re.compile(r"\bv0\.\S+")

# Regex: old tier names as standalone tokens — not part of a larger word
# e.g. "FAST" alone, but not "FAST" inside "FASTEST" or "BROADCAST"
# Also not matched when they appear in comments about the rename itself
_TIER_PATTERNS = {
    name: re.compile(rf"(?<![A-Z_]){name}(?![A-Z_])") for name in _OLD_TIER_NAMES
}


def _is_allowed(path: Path) -> bool:
    return path.name in _ALLOWED_FILES


def run_release_checks(root: Path | None = None) -> list[str]:
    """
    Scan all .md files under *root* (defaults to the repo root) for release
    readiness violations.

    Returns a list of human-readable violation strings.  An empty list means
    the release is clean.
    """
    if root is None:
        root = Path(__file__).parent.parent

    md_files: list[Path] = list(root.glob("*.md")) + list((root / "docs").rglob("*.md"))

    violations: list[str] = []

    for doc in sorted(md_files):
        if _is_allowed(doc):
            continue

        try:
            text = doc.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        rel = doc.relative_to(root)

        # Check for v0.x references
        for m in _V0_PATTERN.finditer(text):
            line_no = text[: m.start()].count("\n") + 1
            violations.append(
                f"{rel}:{line_no}: legacy version reference '{m.group()}'"
            )

        # Check for old tier names
        for tier_name, pattern in _TIER_PATTERNS.items():
            for m in pattern.finditer(text):
                line_no = text[: m.start()].count("\n") + 1
                context = text[max(0, m.start() - 20): m.end() + 20].replace("\n", " ")
                violations.append(
                    f"{rel}:{line_no}: old tier name '{tier_name}' found — "
                    f"rename to STANDARD/COMPLEX/EXPERT  (context: …{context}…)"
                )

    return violations
