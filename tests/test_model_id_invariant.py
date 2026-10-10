# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_model_id_invariant.py — CI gate for COGNIREPO-700-D01.

CLAUDE.md: "Model names only in intelligence/orchestrator/classifier.py. No hardcoding
elsewhere." Pins the exact grep the defect's AC1 specifies as a permanent regression test.

The pattern requires a digit (or, for grok, just the "grok-" prefix, since real grok IDs like
"grok-beta" have no digit) immediately after the model-family word so it catches real model IDs
(claude-sonnet-4-6, gemini-2.0-flash, gpt-4o, grok-beta) without false-positiving on unrelated
"claude-"-prefixed strings that aren't model IDs at all (e.g. interface/tools/sync_claude_memory.py's
"claude-auto-memory" source tag, "claude-memory-sync" action name — neither is a model
identifier).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent

_MODEL_ID_PATTERN = r'"claude-[a-z]+-[0-9]|"gemini-[0-9]|"gpt-[0-9]|"grok-'


def test_no_model_id_literals_outside_classifier():
    """
    grep -rnE '"claude-[a-z]+-[0-9]|"gemini-[0-9]|"gpt-[0-9]|"grok-' intelligence/ interface/
      --include='*.py' | grep -v classifier.py | grep -v tests/
    must return zero hits — see COGNIREPO-700-D01.
    """
    result = subprocess.run(
        ["grep", "-rnE", _MODEL_ID_PATTERN, "intelligence/", "interface/", "--include=*.py"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    hits = [
        line for line in result.stdout.splitlines()
        if "classifier.py" not in line and not re.match(r"^(intelligence|interface)/.*tests/", line)
    ]
    assert not hits, (
        "Model-ID literal(s) found outside classifier.py — hardcode via "
        "DEFAULT_MODELS_BY_PROVIDER or ADAPTER_STANDALONE_DEFAULTS instead:\n"
        + "\n".join(hits)
    )
