# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Pre-call query enhancement — improves user queries before they hit retrieval.

Problem: users are not always good at prompt engineering. Vague queries like
"fix the auth thing" or "that bug again" produce poor retrieval results.
This module uses the BehaviourTracker's accumulated user profile to expand,
clarify, or focus the query before it reaches hybrid_retrieve().

Enhancement strategies (applied in order, first match wins):

1. HOT_SYMBOL   — raw query matches a known high-hit-count symbol name
                  → append "in <file>" to anchor retrieval to known location
2. VAGUE_REF    — query contains vague pronouns ("it", "that", "the thing")
                  → substitute the most recently queried entity
3. TERMINOLOGY  — a word in the query matches the user's domain shorthand
                  → expand to full known term from terminology dict
4. DEPTH_SIGNAL — user has a known depth preference and no explicit signal
                  → append "[detailed]" or "[concise]" hint
5. PASSTHROUGH  — no enhancement applicable, return query unchanged

The enhanced query is passed to hybrid_retrieve(). The original raw query is
still logged in BehaviourTracker so learning is based on what the user typed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from graph.behaviour_tracker import BehaviourTracker

_VAGUE_PATTERN = re.compile(
    r"\b(it|that|this|the thing|the bug|the issue|the problem|the error|the fix)\b",
    re.IGNORECASE,
)

_DEPTH_HINT_PATTERN = re.compile(
    r"\b(detailed|explain|overview|brief|quick|tldr|summary|in depth|step by step)\b",
    re.IGNORECASE,
)

# Stopwords to exclude from terminology expansion
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "it", "in", "on", "at", "to", "for", "of",
    "and", "or", "not", "how", "why", "what", "when", "where", "which",
    "does", "do", "did", "can", "could", "will", "would", "fix", "bug",
    "issue", "error", "code", "file", "function", "class", "method",
})


@dataclass
class EnhancedQuery:
    text: str
    raw: str
    method: str = "PASSTHROUGH"
    expansions: list[str] = field(default_factory=list)

    @property
    def was_enhanced(self) -> bool:
        return self.text != self.raw


def enhance_query(
    raw_query: str,
    behaviour_tracker: "BehaviourTracker | None",
) -> EnhancedQuery:
    """
    Returns an EnhancedQuery. If BehaviourTracker is None or has no data,
    returns PASSTHROUGH (raw query unchanged). Never raises.
    """
    if not behaviour_tracker or not raw_query.strip():
        return EnhancedQuery(text=raw_query, raw=raw_query)

    try:
        return _enhance(raw_query, behaviour_tracker)
    except Exception:  # pylint: disable=broad-except
        return EnhancedQuery(text=raw_query, raw=raw_query)


def _enhance(raw_query: str, bt: "BehaviourTracker") -> EnhancedQuery:
    style = bt.data.get("interaction_style", {})
    query_patterns: list[str] = style.get("query_patterns", [])
    terminology: dict[str, int] = style.get("terminology", {})
    preferred_depth: str = style.get("preferred_depth", "unknown")
    symbol_weights: dict = bt.data.get("symbol_weights", {})

    query_lower = raw_query.lower()

    # 1. HOT_SYMBOL — query references a symbol name we know is frequently queried
    hot_symbols = _get_hot_symbols(symbol_weights, top_k=15)
    for sym_name, _ in hot_symbols:
        if sym_name.lower() in query_lower and sym_name.lower() not in _STOPWORDS:
            expanded = f"{raw_query} [{sym_name}]"
            return EnhancedQuery(
                text=expanded,
                raw=raw_query,
                method="HOT_SYMBOL",
                expansions=[sym_name],
            )

    # 2. VAGUE_REF — substitute most recent entity from query history
    if _VAGUE_PATTERN.search(raw_query):
        last_entity = _last_queried_entity(query_patterns, symbol_weights)
        if last_entity:
            enhanced = _VAGUE_PATTERN.sub(last_entity, raw_query, count=1)
            return EnhancedQuery(
                text=enhanced,
                raw=raw_query,
                method="VAGUE_REF",
                expansions=[last_entity],
            )

    # 3. TERMINOLOGY — expand user shorthand to full known term
    expanded_terms = _expand_terminology(raw_query, terminology)
    if expanded_terms:
        expanded = raw_query + " " + " ".join(expanded_terms)
        return EnhancedQuery(
            text=expanded.strip(),
            raw=raw_query,
            method="TERMINOLOGY",
            expansions=expanded_terms,
        )

    # 4. DEPTH_SIGNAL — user has known depth preference, no explicit signal in query
    if (
        preferred_depth in ("detailed", "concise")
        and not _DEPTH_HINT_PATTERN.search(raw_query)
        and len(raw_query.split()) <= 10
    ):
        hint = "[detailed]" if preferred_depth == "detailed" else "[concise]"
        return EnhancedQuery(
            text=f"{raw_query} {hint}",
            raw=raw_query,
            method="DEPTH_SIGNAL",
            expansions=[hint],
        )

    return EnhancedQuery(text=raw_query, raw=raw_query, method="PASSTHROUGH")


def _get_hot_symbols(symbol_weights: dict, top_k: int = 15) -> list[tuple[str, str]]:
    """Return [(symbol_name, node_id)] sorted by hit_count descending."""
    scored = [
        (node_id, float(v.get("hit_count", 0)))
        for node_id, v in symbol_weights.items()
        if isinstance(v, dict)
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    result = []
    for node_id, _ in scored[:top_k]:
        # node_id format: "symbol::fn_name" or "symbol::ClassName"
        name = node_id.split("::")[-1] if "::" in node_id else node_id
        if name and len(name) > 2:
            result.append((name, node_id))
    return result


def _last_queried_entity(query_patterns: list[str], symbol_weights: dict) -> str | None:
    """Find the most recent non-vague symbol or identifier from query history."""
    hot_names = {n for n, _ in _get_hot_symbols(symbol_weights, top_k=30)}
    _IDENT_RE = re.compile(r'\b([a-z_][a-z0-9_]{2,}|[A-Z][a-zA-Z0-9]{2,})\b')
    for query in reversed(query_patterns[-10:]):
        if _VAGUE_PATTERN.search(query):
            continue
        for match in _IDENT_RE.finditer(query):
            word = match.group(1)
            if word not in _STOPWORDS and (word in hot_names or len(word) > 4):
                return word
    return None


def _expand_terminology(query: str, terminology: dict[str, int]) -> list[str]:
    """
    Find query words that are abbreviations of known terminology.
    E.g. user types "auth" → terminology has "authentication" → expand.
    Only expands if the known term is meaningfully longer (>=2x chars).
    """
    query_words = set(re.findall(r'\b[a-z][a-z0-9_]{2,}\b', query.lower()))
    top_terms = sorted(terminology, key=lambda k: terminology[k], reverse=True)[:30]
    expansions = []
    for abbrev in query_words:
        if abbrev in _STOPWORDS:
            continue
        for term in top_terms:
            if (
                term != abbrev
                and term.startswith(abbrev)
                and len(term) >= len(abbrev) * 2
            ):
                expansions.append(term)
                break
    return expansions[:2]
