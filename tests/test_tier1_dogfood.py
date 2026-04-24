# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Tier-1 dogfood tests — verify the docs index integrates correctly with
the classifier and the router local-resolver.

Uses sys.modules mocking so faiss/sentence-transformers/networkx are not required.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch


def _stub_heavy_deps():
    """Stub out packages that aren't installed in the test environment."""
    for name in ("networkx", "faiss", "sentence_transformers"):
        try:
            __import__(name)
        except ImportError:
            sys.modules[name] = MagicMock()
    # Only set DiGraph on the stub — never mutate the real networkx module.
    if isinstance(sys.modules.get("networkx"), MagicMock):
        sys.modules["networkx"].DiGraph = MagicMock(return_value=MagicMock())


_stub_heavy_deps()


# ── classifier: docs_query override ──────────────────────────────────────────

def test_classifier_routes_cognirepo_question_to_quick():
    from orchestrator.classifier import classify
    result = classify("how do I install cognirepo")
    assert result.tier == "QUICK"
    assert "docs_query" in result.overrides


def test_classifier_routes_mcp_question_to_quick():
    from orchestrator.classifier import classify
    result = classify("what is MCP in cognirepo")
    assert result.tier == "QUICK"
    assert "docs_query" in result.overrides


def test_classifier_docs_override_does_not_fire_for_unrelated():
    from orchestrator.classifier import classify
    result = classify("fix the merge sort algorithm")
    assert "docs_query" not in result.overrides


# ── router: try_local_resolve docs branch ─────────────────────────────────────

def _make_mock_docs_index(score=0.9, text="Install with pip.", file="USAGE.md", section="Install"):
    idx = MagicMock()
    idx.is_docs_query.return_value = True
    idx.answer.return_value = [{"score": score, "text": text, "file": file, "section": section}]
    return idx


def _import_try_local_resolve():
    """Import try_local_resolve with all heavy deps stubbed."""
    # Stub the graph + context builder imports that router pulls in
    for mod in (
        "graph.knowledge_graph", "graph.behaviour_tracker",
        "orchestrator.context_builder",
        "orchestrator.model_adapters.anthropic_adapter",
        "orchestrator.model_adapters.errors",
        "memory.episodic_memory",
    ):
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()

    # Ensure ModelCallError is patchable
    err_mod = sys.modules.setdefault(
        "orchestrator.model_adapters.errors", MagicMock()
    )
    if not hasattr(err_mod, "ModelCallError"):
        err_mod.ModelCallError = type("ModelCallError", (Exception,), {"NON_RETRYABLE_CODES": set(), "message": ""})

    # Stub config.paths
    if "config.paths" not in sys.modules:
        m = types.ModuleType("config.paths")
        m.get_path = lambda *a, **kw: ".cognirepo"
        sys.modules["config.paths"] = m

    from orchestrator.router import try_local_resolve
    return try_local_resolve


def test_try_local_resolve_returns_docs_answer_above_threshold():
    try_local_resolve = _import_try_local_resolve()
    mock_idx = _make_mock_docs_index(score=0.85)

    with patch("cli.docs_index.ensure_docs_index", return_value=mock_idx):
        result = try_local_resolve("how do I install cognirepo", None)

    assert result is not None
    assert "Install with pip." in result
    assert "→ see: USAGE.md" in result


def test_try_local_resolve_ignores_low_confidence_docs():
    try_local_resolve = _import_try_local_resolve()
    mock_idx = _make_mock_docs_index(score=0.4)

    with patch("cli.docs_index.ensure_docs_index", return_value=mock_idx):
        result = try_local_resolve("how do I install cognirepo", None)

    if result is not None:
        assert "→ see:" not in result


def test_try_local_resolve_skips_docs_when_not_docs_query():
    try_local_resolve = _import_try_local_resolve()
    mock_idx = MagicMock()
    mock_idx.is_docs_query.return_value = False

    with patch("cli.docs_index.ensure_docs_index", return_value=mock_idx):
        try_local_resolve("list files", None)

    mock_idx.answer.assert_not_called()


def test_try_local_resolve_handles_docs_index_none():
    """If ensure_docs_index returns None, routing must not crash."""
    try_local_resolve = _import_try_local_resolve()
    with patch("cli.docs_index.ensure_docs_index", return_value=None):
        # Must not raise
        try_local_resolve("how does cognirepo work", None)


def test_try_local_resolve_handles_docs_index_exception():
    """If docs index raises, routing must not crash."""
    try_local_resolve = _import_try_local_resolve()
    with patch("cli.docs_index.ensure_docs_index", side_effect=RuntimeError("boom")):
        try_local_resolve("how does cognirepo work", None)
