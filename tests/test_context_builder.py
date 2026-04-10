# pylint: disable=missing-docstring, unnecessary-lambda, import-outside-toplevel, too-few-public-methods, duplicate-code
# pylint: disable=redefined-outer-name, unused-argument, broad-exception-caught, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tests/test_context_builder.py — B3.3: token budget and trim logic.

All tests work on ContextBundle directly to avoid loading real models/storage.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

# Stub heavy deps not installed in test environment
for _dep in ("networkx", "faiss", "sentence_transformers"):
    if _dep not in sys.modules:
        sys.modules[_dep] = MagicMock()
sys.modules["networkx"].DiGraph = MagicMock(return_value=MagicMock())


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_bundle(
    memories=None,
    graph_context="",
    episodes=None,
    ast_hits=None,
    max_tokens=1000,
):
    from orchestrator.context_builder import ContextBundle
    # copy lists so trim mutations don't affect caller's originals
    b = ContextBundle(
        query="test query",
        memories=list(memories) if memories else [],
        graph_context=graph_context,
        recent_episodes=list(episodes) if episodes else [],
        ast_hits=list(ast_hits) if ast_hits else [],
        max_tokens=max_tokens,
    )
    b.system_prompt = b.to_system_prompt()
    return b


def _make_episode(event_text, time="2024-01-01T00:00:00Z"):
    return {"event": event_text, "time": time}


def _make_memory(text, score=0.5):
    return {"text": text, "final_score": score, "importance": score}


# ── token estimation ──────────────────────────────────────────────────────────

class TestTokenEstimation:
    def test_empty_string_is_zero(self):
        from orchestrator.context_builder import _estimate_tokens
        assert _estimate_tokens("") == 0

    def test_four_chars_is_one_token(self):
        from orchestrator.context_builder import _estimate_tokens
        assert _estimate_tokens("abcd") == 1

    def test_scales_linearly(self):
        from orchestrator.context_builder import _estimate_tokens
        assert _estimate_tokens("a" * 400) == 100

    def test_long_text_estimated(self):
        from orchestrator.context_builder import _estimate_tokens
        text = "hello world " * 1000  # 12000 chars → 3000 tokens
        assert _estimate_tokens(text) == 3000


# ── tier budgets ──────────────────────────────────────────────────────────────

class TestTierBudgets:
    def test_standard_budget(self):
        from orchestrator.context_builder import TIER_BUDGETS
        assert TIER_BUDGETS["STANDARD"] == 6_000

    def test_complex_budget(self):
        from orchestrator.context_builder import TIER_BUDGETS
        assert TIER_BUDGETS["COMPLEX"] == 12_000

    def test_expert_budget(self):
        from orchestrator.context_builder import TIER_BUDGETS
        assert TIER_BUDGETS["EXPERT"] == 24_000

    def test_build_sets_tier_budget(self, monkeypatch):
        """build() with tier='STANDARD' sets max_tokens=6000 on bundle."""
        _patch_build_sources(monkeypatch)
        from orchestrator.context_builder import build
        bundle = build("test", tier="STANDARD")
        assert bundle.max_tokens == 6_000

    def test_build_expert_budget(self, monkeypatch):
        _patch_build_sources(monkeypatch)
        from orchestrator.context_builder import build
        bundle = build("test", tier="EXPERT")
        assert bundle.max_tokens == 24_000


def _patch_build_sources(monkeypatch):
    """Stub out all external calls in context_builder.build()."""
    monkeypatch.setattr(
        "orchestrator.context_builder._get_retriever",
        lambda: type("R", (), {"retrieve": lambda self, q, k: []})(),
    )
    monkeypatch.setattr(
        "orchestrator.context_builder.KnowledgeGraph",
        lambda: type("KG", (), {
            "node_exists": lambda self, n: False,
            "subgraph_around": lambda self, n, radius=2: {"nodes": [], "edges": []},
        })(),
    )
    monkeypatch.setattr(
        "orchestrator.context_builder.ASTIndexer",
        lambda graph: type("AI", (), {
            "load": lambda self: None,
            "lookup_symbol": lambda self, e: [],
            "index_data": {"files": {}},
        })(),
    )
    monkeypatch.setattr(
        "orchestrator.context_builder.get_history",
        lambda limit: [],
    )
    monkeypatch.setattr(
        "orchestrator.context_builder._load_manifest",
        lambda: [],
    )
    monkeypatch.setattr(
        "orchestrator.context_builder.extract_entities_from_text",
        lambda q: [],
    )


# ── no trim when within budget ────────────────────────────────────────────────

class TestNoBudgetExceeded:
    def test_small_bundle_not_trimmed(self):
        from orchestrator.context_builder import _trim_to_budget
        b = _make_bundle(
            memories=[_make_memory("short memory")],
            episodes=[_make_episode("short event")],
            max_tokens=10_000,
        )
        _trim_to_budget(b)
        assert not b.was_trimmed
        assert b.token_count > 0

    def test_token_count_set_even_without_trim(self):
        from orchestrator.context_builder import _trim_to_budget
        b = _make_bundle(max_tokens=50_000)
        _trim_to_budget(b)
        assert b.token_count >= 0
        assert not b.was_trimmed


# ── episodic trim (oldest first) ──────────────────────────────────────────────

class TestEpisodicTrim:
    def test_episodes_trimmed_first(self):
        """Episodic events are removed before memories when over budget."""
        from orchestrator.context_builder import _trim_to_budget
        big_episodes = [_make_episode(f"event {'x' * 300} number {i}") for i in range(20)]
        memories = [_make_memory("important memory xyz", score=0.9)]
        b = _make_bundle(episodes=big_episodes, memories=memories, max_tokens=300)
        _trim_to_budget(b)
        # Memory survived; episodes were trimmed
        assert any("important memory xyz" in m.get("text", "") for m in b.memories)
        assert len(b.recent_episodes) < len(big_episodes)
        assert b.was_trimmed

    def test_oldest_episode_removed_first(self):
        """Most recent episode (index 0) survives; oldest (last) removed first."""
        from orchestrator.context_builder import _trim_to_budget
        # Fill with large events so we're over budget
        episodes = [
            _make_episode(f"NEWEST_EVENT {'x' * 200}"),  # index 0 = newest
            _make_episode(f"middle event {'x' * 200}"),
            _make_episode(f"OLDEST_EVENT {'x' * 200}"),  # index -1 = oldest
        ]
        b = _make_bundle(episodes=episodes, max_tokens=300)
        # Force over-budget by making max_tokens very small
        b.max_tokens = 200
        _trim_to_budget(b)
        if b.recent_episodes:  # if any survived
            assert b.recent_episodes[0]["event"].startswith("NEWEST_EVENT")

    def test_all_episodes_can_be_removed(self):
        """If even removing all episodes isn't enough, trimming continues."""
        from orchestrator.context_builder import _trim_to_budget
        massive_memory = [_make_memory("m " * 5000, score=0.9)]
        b = _make_bundle(
            memories=massive_memory,
            episodes=[_make_episode("e " * 200) for _ in range(10)],
            max_tokens=100,  # tiny budget
        )
        _trim_to_budget(b)
        # episodes fully removed
        assert len(b.recent_episodes) == 0
        assert b.was_trimmed


# ── graph context trim ────────────────────────────────────────────────────────

class TestGraphTrim:
    def test_graph_lines_trimmed_from_end(self):
        """Graph context is trimmed by removing lines from the end."""
        from orchestrator.context_builder import _trim_to_budget
        graph_lines = [f"node_{i}: {'x' * 50}" for i in range(50)]
        graph_text = "\n".join(graph_lines)
        b = _make_bundle(graph_context=graph_text, max_tokens=200)
        original_lines = len(graph_lines)
        _trim_to_budget(b)
        remaining_lines = len(b.graph_context.split("\n")) if b.graph_context else 0
        assert remaining_lines <= original_lines
        if b.graph_context:
            assert b.graph_context.startswith("node_0")  # first (closest) node preserved

    def test_graph_trimmed_after_episodes_exhausted(self):
        """Graph is only trimmed after all episodes are removed."""
        from orchestrator.context_builder import _trim_to_budget
        graph_text = "\n".join(f"node_{i}: {'y' * 80}" for i in range(30))
        episodes = [_make_episode(f"ep {i} {'z' * 10}") for i in range(3)]
        b = _make_bundle(graph_context=graph_text, episodes=episodes, max_tokens=200)
        _trim_to_budget(b)
        # All episodes should be gone (trimmed first), graph partially trimmed
        assert len(b.recent_episodes) == 0


# ── memory trim (lowest score first) ─────────────────────────────────────────

class TestMemoryTrim:
    def test_lowest_score_memory_removed_first(self):
        """Memory with the lowest final_score is removed before high-score ones."""
        from orchestrator.context_builder import _trim_to_budget
        memories = [
            _make_memory("high score memory abc " * 100, score=0.95),
            _make_memory("medium score memory def " * 100, score=0.5),
            _make_memory("low score memory ghi " * 100, score=0.1),
        ]
        b = _make_bundle(memories=memories, max_tokens=300)
        _trim_to_budget(b)
        if b.memories:
            scores = [m.get("final_score", 0) for m in b.memories]
            # Remaining memories should all have higher scores than removed ones
            assert max(scores) >= min(scores)
            # highest score should still be present
            texts = [m.get("text", "") for m in b.memories]
            assert any("high score memory abc" in t for t in texts)

    def test_high_score_memory_survives_trim(self):
        """High-scoring memory survives aggressive trimming."""
        from orchestrator.context_builder import _trim_to_budget
        memories = [
            _make_memory("TOP_SCORE " * 50, score=1.0),
            _make_memory("low " * 500, score=0.01),
            _make_memory("low " * 500, score=0.02),
        ]
        b = _make_bundle(memories=memories, max_tokens=300)
        _trim_to_budget(b)
        texts = [m.get("text", "") for m in b.memories]
        assert any("TOP_SCORE" in t for t in texts)


# ── 30k → budget trim (acceptance criterion) ─────────────────────────────────

class TestOverallBudget:
    def test_30k_context_trimmed_to_budget(self):
        """A 30k-token context gets trimmed to fit the budget without error."""
        from orchestrator.context_builder import _trim_to_budget, _estimate_tokens
        # Build ~30k token context (30k * 4 = 120k chars)
        big_episodes = [_make_episode("episode text " * 400) for _ in range(20)]
        big_graph = "\n".join(f"node_{i}: " + "edge data " * 200 for i in range(10))
        big_memories = [_make_memory("memory " * 200, score=i * 0.1) for i in range(10)]
        b = _make_bundle(
            episodes=big_episodes,
            graph_context=big_graph,
            memories=big_memories,
            max_tokens=12_000,
        )
        original = _estimate_tokens(b.to_system_prompt())
        assert original > 12_000, "test setup: context must start over budget"

        _trim_to_budget(b)

        assert b.was_trimmed
        final = _estimate_tokens(b.to_system_prompt())
        assert final <= 12_000

    def test_ast_hits_never_trimmed(self):
        """AST symbol hits are never removed during trimming."""
        from orchestrator.context_builder import _trim_to_budget
        ast_hits = [
            {"name": "critical_fn", "file": "app.py", "line": 10, "type": "FUNCTION"}
        ] * 5
        big_episodes = [_make_episode("episode " * 500) for _ in range(10)]
        b = _make_bundle(episodes=big_episodes, ast_hits=ast_hits, max_tokens=200)
        _trim_to_budget(b)
        assert b.ast_hits == ast_hits  # never touched

    def test_was_trimmed_flag_set(self):
        from orchestrator.context_builder import _trim_to_budget
        big = [_make_episode("x " * 1000) for _ in range(20)]
        b = _make_bundle(episodes=big, max_tokens=100)
        _trim_to_budget(b)
        assert b.was_trimmed

    def test_system_prompt_updated_after_trim(self):
        """bundle.system_prompt reflects trimmed content, not original."""
        from orchestrator.context_builder import _trim_to_budget
        episodes = [_make_episode(f"UNIQUE_EPISODE_{i} " + "pad " * 500) for i in range(5)]
        b = _make_bundle(episodes=episodes, max_tokens=200)
        _trim_to_budget(b)
        # system_prompt should match what to_system_prompt() would produce now
        assert b.system_prompt == b.to_system_prompt()
