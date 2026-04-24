# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Complexity Classifier — rule-based, multi-signal weighted scorer.
No ML training required. Decides QUICK / STANDARD / COMPLEX / EXPERT tier for every query.

Signal table (from ARCHITECTURE.md):
┌────────────────────────────────────────────────┬────────┬──────────────────────────┐
│ Signal                                         │ Weight │ Logic                    │
├────────────────────────────────────────────────┼────────┼──────────────────────────┤
│ Reasoning keywords (why,compare,refactor,…)    │  +3    │ per keyword found        │
│ Lookup keywords (what is,show,list,find,get)   │  -2    │ per keyword found        │
│ Vague referents (it,this,that w/o clear noun)  │  +2    │ per unresolved ref       │
│ Cross-entity count (fn/file/class mentions)    │  +1.5  │ per entity above 2       │
│ Context dependency (episodic/graph history ref)│  +3    │ binary                   │
│ Query token length                             │ +0.5   │ per 10 tok after first 20│
│ Imperative+abstract combo (implement,build,…) │  +5    │ binary                   │
└────────────────────────────────────────────────┴────────┴──────────────────────────┘

Tiers:   ≤2 → QUICK (local resolver)   ≤4 → STANDARD   ≤9 → COMPLEX   >9 → EXPERT

Hard overrides (bypass score):
  "full context" / "everything related"   → EXPERT
  single word / single symbol             → QUICK (fastest path)
  error trace in query                    → COMPLEX minimum
"""
import json
import os
import re
from dataclasses import dataclass, field

from config.paths import get_path

def _config_file() -> str:
    return get_path("config.json")

# ── keyword sets ──────────────────────────────────────────────────────────────
_REASONING_KW = {
    "why", "compare", "refactor", "design", "tradeoff", "trade-off",
    "architecture", "explain", "difference", "versus", "vs", "pros",
    "cons", "evaluate", "analyse", "analyze", "suggest", "recommend",
    # depth/quality modifiers
    "detail", "detailed", "improve", "improvements", "thorough",
    "comprehensive", "complex", "advanced", "in-depth", "deep dive",
    # security / reliability — require multi-file cross-cutting analysis
    "security", "vulnerability", "vulnerabilities", "audit", "exploit",
    "attack surface", "injection", "authentication", "authorization",
    # performance / scalability — need call-graph and hot-path understanding
    "performance", "bottleneck", "optimize", "optimization", "latency",
    "throughput", "scalability", "scalable", "reliability", "reliable",
    # guided walkthrough — explicit request for detailed step-by-step response
    "step by step", "walk me through", "walk through",
}
_LOOKUP_KW = {
    "what is", "what are", "show", "list", "find", "get", "display",
    "print", "fetch", "retrieve", "where is", "which",
}
_IMPERATIVE_ABSTRACT = {
    "implement", "build", "architect", "create", "design", "write",
    "develop", "engineer", "scaffold", "generate",
}
_CONTEXT_DEP = {
    "last time", "earlier", "previously", "history", "before",
    "session", "remember", "recall", "as discussed", "you said",
    "what i", "my last",
    # repo-scoped signals — query is about THIS codebase, not generic knowledge
    "in this repo", "in our repo", "in our codebase", "in my project",
    "in this codebase", "in this project", "our implementation",
    "our code", "this codebase", "this repo",
}
_FULL_CONTEXT = {"full context", "everything related", "all related", "complete context"}
_DOCS_QUERY_PATTERN = re.compile(
    r"\b(cognirepo|install|tier|mcp|prune|doctor|serve.api|retrieve|store|"
    r"how does|what is cognirepo|index.repo|memory|graph|embedding)\b",
    re.IGNORECASE,
)
_ERROR_PATTERNS = re.compile(
    r"(traceback|error:|exception:|syntaxerror|typeerror|nameerror|"
    r"attributeerror|importerror|valueerror|keyerror|indexerror|"
    r"runtimeerror|\bat line \d+|\bline \d+|stacktrace)",
    re.IGNORECASE,
)

# ── tier → score boundaries ───────────────────────────────────────────────────
# These constants are the single source of truth for tier thresholds.
# The table in ARCHITECTURE.md § "Complexity Classifier Signals" mirrors them.
# Update both together — a sync test enforces parity: tests/test_docs_sync.py
_TIER_QUICK    = 2.0
_TIER_STANDARD = 4.0    # formerly FAST
_TIER_COMPLEX  = 9.0    # formerly BALANCED
# 15+ → EXPERT (formerly DEEP)

# Old tier name → new tier name (for config migration)
_LEGACY_TIER_MAP = {
    "FAST": "STANDARD",
    "BALANCED": "COMPLEX",
    "DEEP": "EXPERT",
}


class ConfigMigrationError(RuntimeError):
    """Raised when config.json uses deprecated tier names."""


@dataclass
class ClassifierResult:
    """Result of the query complexity classification."""
    tier: str                          # "QUICK" | "STANDARD" | "COMPLEX" | "EXPERT"
    score: float
    model: str                         # resolved model ID
    provider: str                      # "anthropic" | "gemini" | "grok" | "openai"
    signals: dict[str, float] = field(default_factory=dict)
    overrides: list[str] = field(default_factory=list)


def _resolve_provider(provider: str) -> str:
    """Resolve 'auto' provider by checking env vars in priority order."""
    if provider != "auto":
        return provider
    for p, env in [
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("gemini",    "GEMINI_API_KEY"),
        ("openai",    "OPENAI_API_KEY"),
    ]:
        if os.environ.get(env):
            return p
    return "anthropic"  # fallback


def _load_model_registry() -> dict:
    default = {
        "QUICK":    {"provider": "local",     "model": "local-resolver"},
        "STANDARD": {"provider": "anthropic", "model": "claude-haiku-4-5"},
        "COMPLEX":  {"provider": "anthropic", "model": "claude-sonnet-4-6"},
        "EXPERT":   {"provider": "anthropic", "model": "claude-opus-4-6"},
    }
    if not os.path.exists(_config_file()):
        return default
    try:
        with open(_config_file(), encoding="utf-8") as f:
            cfg = json.load(f)

        # New schema: single "model" key — expand to per-tier registry
        if "model" in cfg and "models" not in cfg:
            single = cfg["model"]
            provider = _resolve_provider(single.get("provider", "auto"))
            model_id = single.get("model", "auto")
            # QUICK always stays local; other tiers use configured provider
            expanded = {
                "QUICK":    {"provider": "local",  "model": "local-resolver"},
                "STANDARD": {"provider": provider, "model": model_id if model_id != "auto" else "claude-haiku-4-5"},
                "COMPLEX":  {"provider": provider, "model": model_id if model_id != "auto" else "claude-sonnet-4-6"},
                "EXPERT":   {"provider": provider, "model": model_id if model_id != "auto" else "claude-opus-4-6"},
            }
            return expanded

        # Legacy multi-tier schema — still supported for existing installs
        models = cfg.get("models", default)
        legacy_found = [k for k in models if k in _LEGACY_TIER_MAP]
        if legacy_found:
            raise ConfigMigrationError(
                f"config.json uses deprecated tier names: {legacy_found}. "
                "Rename FAST→STANDARD, BALANCED→COMPLEX, DEEP→EXPERT. "
                "Auto-fix: cognirepo migrate-config"
            )
        return models
    except (json.JSONDecodeError, OSError):
        return default


def classify(
    query: str,
    context: dict | None = None,
    force_model: str | None = None,
) -> ClassifierResult:
    """
    Classify a query and return a ClassifierResult with tier, score, model,
    per-signal breakdown, and any hard override labels.

    Parameters
    ----------
    query       : raw query string
    context     : optional dict with keys like "has_episodic_ref", "entities"
    force_model : override model ID (e.g. "claude-opus-4-6") — tier still computed
    """
    q = query.strip()
    q_lower = q.lower()
    tokens = q_lower.split()
    registry = _load_model_registry()
    signals: dict[str, float] = {}
    overrides: list[str] = []

    # ── hard overrides ────────────────────────────────────────────────────────
    if len(tokens) <= 1:
        tier = "QUICK"
        overrides.append("single_token")
        score = 0.0
    elif _DOCS_QUERY_PATTERN.search(q):
        tier = "QUICK"
        overrides.append("docs_query")
        score = 0.0
    elif any(p in q_lower for p in _FULL_CONTEXT):
        tier = "EXPERT"
        overrides.append("full_context_phrase")
        score = 20.0
    elif _ERROR_PATTERNS.search(q):
        tier = "COMPLEX"           # minimum; scoring may push to EXPERT
        overrides.append("error_trace")
        score = _compute_score(q_lower, tokens, context, signals)
        if score >= _TIER_COMPLEX:
            tier = "EXPERT"
    else:
        score = _compute_score(q_lower, tokens, context, signals)
        tier = _score_to_tier(score)

    # resolve model from registry (force_model overrides model ID, not tier)
    reg_entry = registry.get(tier, registry.get("EXPERT", {}))
    provider = reg_entry.get("provider", "anthropic")
    model_id = force_model or reg_entry.get("model", "claude-sonnet-4-6")

    return ClassifierResult(
        tier=tier,
        score=round(score, 2),
        model=model_id,
        provider=provider,
        signals=signals,
        overrides=overrides,
    )


def _compute_score(
    q_lower: str,
    tokens: list[str],
    context: dict | None,
    signals: dict,
) -> float:
    score = 0.0

    # reasoning keywords (+3 each)
    r_hits = sum(1 for kw in _REASONING_KW if kw in q_lower)
    if r_hits:
        signals["reasoning_keywords"] = r_hits * 3.0
        score += signals["reasoning_keywords"]

    # lookup keywords (-2 each)
    l_hits = sum(1 for kw in _LOOKUP_KW if kw in q_lower)
    if l_hits:
        signals["lookup_keywords"] = -(l_hits * 2.0)
        score += signals["lookup_keywords"]

    # vague referents (+2 each unresolved)
    vague = _count_vague_referents(tokens)
    if vague:
        signals["vague_referents"] = vague * 2.0
        score += signals["vague_referents"]

    # cross-entity count (+1.5 per entity above 2)
    entities = _extract_entities(q_lower)
    extra = max(0, len(entities) - 2)
    if extra:
        signals["cross_entity_count"] = extra * 1.5
        score += signals["cross_entity_count"]

    # context dependency (+3 binary)
    has_ctx = any(p in q_lower for p in _CONTEXT_DEP)
    if not has_ctx and context:
        has_ctx = context.get("has_episodic_ref", False)
    if has_ctx:
        signals["context_dependency"] = 3.0
        score += 3.0

    # token length (+0.5 per 10 tokens after first 20)
    tok_excess = max(0, len(tokens) - 20)
    if tok_excess:
        tl = (tok_excess / 10) * 0.5
        signals["token_length"] = round(tl, 2)
        score += tl

    # imperative + abstract combo (+5 binary)
    if any(kw in q_lower for kw in _IMPERATIVE_ABSTRACT):
        signals["imperative_abstract"] = 5.0
        score += 5.0

    return score


def _score_to_tier(score: float) -> str:
    if score <= _TIER_QUICK:
        return "QUICK"
    if score <= _TIER_STANDARD:
        return "STANDARD"
    if score <= _TIER_COMPLEX:
        return "COMPLEX"
    return "EXPERT"


def _count_vague_referents(tokens: list[str]) -> int:
    """Count 'it', 'this', 'that' tokens not immediately preceded by a noun/code token."""
    vague = {"it", "this", "that", "they", "them"}
    count = 0
    for i, tok in enumerate(tokens):
        if tok in vague:
            # check if previous token is a noun-like (contains letter + underscore or camelCase)
            prev = tokens[i - 1] if i > 0 else ""
            if not re.search(r"[a-zA-Z_]{3,}", prev):
                count += 1
    return count


def _extract_entities(q_lower: str) -> list[str]:
    """Lightweight entity detector — snake_case, CamelCase, file paths."""
    found: set[str] = set()
    for tok in re.split(r"[\s,;:\"'()\[\]{}]+", q_lower):
        tok = tok.strip(".")
        if not tok or len(tok) < 2:
            continue
        if "_" in tok and tok.replace("_", "").isalpha():
            found.add(tok)
        elif re.search(r"\.[a-z]{1,4}$", tok):
            found.add(tok)
    return list(found)
