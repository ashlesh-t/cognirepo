# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Context builder — hydrates a ContextBundle from all CogniRepo sources
for injection into model prompts.

Sources:
  • Hybrid retrieval   — top-k semantically relevant memories
  • Knowledge graph    — subgraph around query entities (formatted text)
  • Episodic log       — recent N events
  • AST reverse index  — symbol locations matching query entities
  • Tool manifest      — CogniRepo tool schemas for function-calling

Token budget
  • FAST      6 000 tokens
  • BALANCED 12 000 tokens  (default)
  • DEEP     24 000 tokens

When over budget, sources are trimmed in this priority order (least → most
important):
  1. Episodic events  — oldest events removed first
  2. Graph context    — lines removed from end (furthest nodes first)
  3. Semantic memories— lowest-scored memories removed first
  Protected (never trimmed): AST symbol hits, system header
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

from graph.graph_utils import extract_entities_from_text, format_subgraph_for_context
from graph.knowledge_graph import KnowledgeGraph
from indexer.ast_indexer import ASTIndexer
from memory.episodic_memory import get_history
from retrieval.hybrid import HybridRetriever

logger = logging.getLogger(__name__)

MANIFEST_PATH = "server/manifest.json"

#: Token budget per classifier tier (rough: 1 token ≈ 4 chars)
TIER_BUDGETS: dict[str, int] = {
    "FAST":     6_000,
    "BALANCED": 12_000,
    "DEEP":     24_000,
}

# lazily-shared retriever instance for context_builder calls within one session
_shared_retriever: HybridRetriever | None = None


def _get_retriever() -> HybridRetriever:
    global _shared_retriever  # pylint: disable=global-statement
    if _shared_retriever is None:
        _shared_retriever = HybridRetriever()
    return _shared_retriever


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token ≈ 4 characters."""
    return max(0, len(text) // 4)


@dataclass
class ContextBundle:
    query: str
    memories: list[dict] = field(default_factory=list)       # hybrid retrieval results
    graph_context: str = ""                                   # formatted subgraph text
    recent_episodes: list[dict] = field(default_factory=list)
    ast_hits: list[dict] = field(default_factory=list)        # reverse-index symbol hits
    tool_manifest: list[dict] = field(default_factory=list)   # CogniRepo tool schemas
    system_prompt: str = ""                                   # assembled for model
    # token budget tracking
    max_tokens: int = TIER_BUDGETS["BALANCED"]
    token_count: int = 0                                      # tokens after trimming
    was_trimmed: bool = False

    def to_system_prompt(self) -> str:
        """Assemble all context sources into a single system prompt string."""
        parts: list[str] = [
            "You are CogniRepo — a cognitive infrastructure layer for AI agents. "
            "You have access to the developer's semantic memory, codebase index, "
            "episodic history, and knowledge graph.",
        ]

        if self.memories:
            parts.append("\n## Relevant Memories")
            for i, m in enumerate(self.memories[:5], 1):
                score = m.get("final_score", m.get("importance", "?"))
                parts.append(f"{i}. [{score}] {m.get('text', '')}")

        if self.graph_context and self.graph_context != "(empty graph)":
            parts.append("\n## Knowledge Graph Context")
            parts.append(self.graph_context)

        if self.ast_hits:
            parts.append("\n## Codebase Symbol Hits")
            for h in self.ast_hits[:6]:
                parts.append(f"  • {h['file']}:{h['line']}  [{h.get('type','?')}] {h['name']}")

        if self.recent_episodes:
            parts.append("\n## Recent Episodic Context (last events)")
            for ev in self.recent_episodes[:5]:
                parts.append(f"  [{ev.get('time','?')}] {ev.get('event','')}")

        return "\n".join(parts)


def build(
    query: str,
    top_k: int = 5,
    episode_limit: int = 10,
    tier: str = "BALANCED",
) -> ContextBundle:
    """
    Build a ContextBundle for the given query, trimmed to the tier's token budget.

    Parameters
    ----------
    query         : the raw user query
    top_k         : how many memories to retrieve
    episode_limit : how many recent episodic events to include
    tier          : classifier tier — controls token budget (FAST/BALANCED/DEEP)
    """
    bundle = ContextBundle(
        query=query,
        max_tokens=TIER_BUDGETS.get(tier, TIER_BUDGETS["BALANCED"]),
    )

    # ── 1. hybrid memory retrieval ────────────────────────────────────────────
    try:
        retriever = _get_retriever()
        bundle.memories = retriever.retrieve(query, top_k)
    except Exception:  # pylint: disable=broad-except
        bundle.memories = []

    # ── 2. knowledge graph subgraph ───────────────────────────────────────────
    try:
        kg = KnowledgeGraph()
        entities = extract_entities_from_text(query)
        subgraph_nodes: list[dict] = []
        subgraph_edges: list[dict] = []
        for entity in entities[:3]:  # limit to 3 focal entities
            for node_id in [entity, f"concept::{entity.lower()}", f"symbol::{entity}"]:
                if kg.node_exists(node_id):
                    sg = kg.subgraph_around(node_id, radius=2)
                    subgraph_nodes.extend(sg.get("nodes", []))
                    subgraph_edges.extend(sg.get("edges", []))
                    break
        # deduplicate nodes
        seen_ids: set[str] = set()
        deduped_nodes = []
        for n in subgraph_nodes:
            nid = n.get("node_id", "")
            if nid and nid not in seen_ids:
                seen_ids.add(nid)
                deduped_nodes.append(n)
        bundle.graph_context = format_subgraph_for_context(
            {"nodes": deduped_nodes, "edges": subgraph_edges}
        )
    except Exception:  # pylint: disable=broad-except
        bundle.graph_context = ""

    # ── 3. episodic history ───────────────────────────────────────────────────
    try:
        bundle.recent_episodes = get_history(episode_limit)
    except Exception:  # pylint: disable=broad-except
        bundle.recent_episodes = []

    # ── 4. AST reverse index hits ─────────────────────────────────────────────
    try:
        kg2 = KnowledgeGraph()
        indexer = ASTIndexer(graph=kg2)
        indexer.load()
        entities2 = extract_entities_from_text(query)
        hits: list[dict] = []
        seen_hits: set[str] = set()
        for ent in entities2:
            for loc in indexer.lookup_symbol(ent):
                key = f"{loc['file']}:{loc['line']}"
                if key not in seen_hits:
                    seen_hits.add(key)
                    # pull type from index
                    file_data = indexer.index_data.get("files", {}).get(loc["file"], {})
                    sym = next(
                        (s for s in file_data.get("symbols", []) if s["name"] == ent),
                        {}
                    )
                    hits.append({
                        "name": ent,
                        "file": loc["file"],
                        "line": loc["line"],
                        "type": sym.get("type", "SYMBOL"),
                    })
        bundle.ast_hits = hits[:10]
    except Exception:  # pylint: disable=broad-except
        bundle.ast_hits = []

    # ── 5. tool manifest ─────────────────────────────────────────────────────
    bundle.tool_manifest = _load_manifest()

    # ── 6. assemble + trim to budget ─────────────────────────────────────────
    bundle.system_prompt = bundle.to_system_prompt()
    _trim_to_budget(bundle)

    return bundle


# ── token budget trimming ─────────────────────────────────────────────────────

def _trim_to_budget(bundle: ContextBundle) -> None:
    """
    Trim bundle sources until system_prompt fits within bundle.max_tokens.

    Trim order (least to most important):
      1. Episodic events — oldest first (last items in the list, which is newest-first)
      2. Graph context   — lines from end (furthest nodes)
      3. Memories        — lowest final_score first
    Never trimmed: AST hits, system header.
    """
    original_tokens = _estimate_tokens(bundle.to_system_prompt())
    if original_tokens <= bundle.max_tokens:
        bundle.token_count = original_tokens
        return

    budget = bundle.max_tokens

    # ── step 1: trim episodic events (oldest = last item) ────────────────────
    while bundle.recent_episodes:
        if _estimate_tokens(bundle.to_system_prompt()) <= budget:
            break
        bundle.recent_episodes.pop()  # remove oldest episode

    # ── step 2: trim graph context (remove lines from end = furthest nodes) ──
    if _estimate_tokens(bundle.to_system_prompt()) > budget and bundle.graph_context:
        lines = bundle.graph_context.split("\n")
        while lines and _estimate_tokens(bundle.to_system_prompt()) > budget:
            lines.pop()
            bundle.graph_context = "\n".join(lines)

    # ── step 3: trim memories (lowest score first) ────────────────────────────
    if _estimate_tokens(bundle.to_system_prompt()) > budget and bundle.memories:
        # sort descending by score so we can pop() the lowest
        bundle.memories = sorted(
            bundle.memories,
            key=lambda m: float(m.get("final_score", m.get("importance", 0)) or 0),
            reverse=True,
        )
        while bundle.memories and _estimate_tokens(bundle.to_system_prompt()) > budget:
            bundle.memories.pop()

    final_tokens = _estimate_tokens(bundle.to_system_prompt())
    bundle.token_count = final_tokens
    bundle.was_trimmed = True

    logger.debug(
        "Context trimmed: %d → %d tokens (budget: %d)",
        original_tokens, final_tokens, budget,
    )

    # Re-assemble system_prompt with trimmed sources
    bundle.system_prompt = bundle.to_system_prompt()


def _load_manifest() -> list[dict]:
    """Load tool schemas from server/manifest.json, generating it if absent."""
    if not os.path.exists(MANIFEST_PATH):
        try:
            from server.mcp_server import _write_manifest  # lazy import
            _write_manifest()
        except Exception:  # pylint: disable=broad-except
            return []
    try:
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("tools", [])
    except (json.JSONDecodeError, OSError):
        return []
