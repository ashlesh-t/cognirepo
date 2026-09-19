# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
intelligence/precedent_check.py — grounded pushback (COGNIREPO-704).

Before implementing a non-trivial instruction, check whether it contradicts a recorded
decision or a CLAUDE.md invariant, and if so surface the conflict with a citation and a
concrete alternative — instead of silently complying. NEVER auto-blocks: this is advisory
only, same as the existing Gate 1/Gate 2 review model in skill.md §F — the human's final call
still stands.

Two independent checks, both rule-based (no ML, matching classifier.py's own philosophy):

1. Invariants — a small, structured, machine-checkable registry mirroring CLAUDE.md's "Key
   rules" (today unstructured prose that nothing can cross-reference programmatically).
   Conservative regex triggers: both a "doing this" cue and a topic cue must match, so a
   merely-informational question ("what model does COMPLEX use?") never fires.

2. Decisions — only even looked at when the instruction itself contains a reversal/negation
   cue ("instead of", "replace", "stop using", ...); an ordinary request never triggers a
   decision search at all. When a cue is present, the closest-matching recorded decision (via
   the same BM25 machinery search_episodes()/find_consolidation_candidates() already use) is
   surfaced as a citation — this is a low-recall, low-false-positive design deliberately: the
   risk of an over-eager "well actually" on a routine ask outweighs catching every possible
   reversal.
"""
from __future__ import annotations

import re

# ── invariants registry (COGNIREPO-704) ────────────────────────────────────────
# Mirrors CLAUDE.md's "Key rules" section. Keep both in sync when either changes.
_INVARIANTS: list[dict] = [
    {
        "name": "model_names_only_in_classifier",
        "citation": "CLAUDE.md — “Model names only in intelligence/orchestrator/classifier.py. "
                     "No hardcoding elsewhere.”",
        "related_defect": "COGNIREPO-700-D01",
        "description": (
            "Hardcoding a model-ID literal outside classifier.py violates this repo's "
            "invariant — exactly the pattern COGNIREPO-700-D01 found and fixed at 4 "
            "sites (model_adapters/*.py, key_probes.py, router.py)."
        ),
        "alternative": (
            "Import the model ID from classifier.py's DEFAULT_MODELS_BY_PROVIDER or "
            "ADAPTER_STANDALONE_DEFAULTS instead of hardcoding it."
        ),
        # Both a hardcoding-intent cue AND a model-ID-shaped token must match —
        # an informational question about models never fires this.
        "intent_pattern": re.compile(
            r"\b(hardcod\w*|hard.code\w*|literal\s+default|inline\s+default|"
            r"default\s*=|defaults?\s+\S+\s+to\s+[\"']?(claude|gemini|gpt|grok)-|"
            r"don'?t\s+(bother\s+)?import\w*\s+from\s+classifier)\b", re.IGNORECASE,
        ),
        "topic_pattern": re.compile(
            r"\b(claude|gemini|gpt|grok)-[a-z0-9][a-z0-9.-]*\b", re.IGNORECASE,
        ),
    },
    {
        "name": "retrieval_only_via_hybrid",
        "citation": "CLAUDE.md — “intelligence/retrieval/hybrid.py owns all retrieval. "
                     "Never call FAISS or the graph directly from tools.”",
        "related_defect": None,
        "description": "Calling FAISS or the knowledge graph directly from a tool bypasses hybrid.py.",
        "alternative": "Route the new retrieval logic through intelligence/retrieval/hybrid.py instead.",
        "intent_pattern": re.compile(
            r"\b(call|query|hit|use)\s+(faiss|the\s+graph)\s+direct\w*\b|"
            r"\bbypass\w*\s+hybrid\b", re.IGNORECASE,
        ),
        "topic_pattern": re.compile(r"\b(tool|tools)\b", re.IGNORECASE),
    },
    {
        "name": "tools_stateless_single_entry_point",
        "citation": "CLAUDE.md — “Tools in interface/tools/ are the single entry point. "
                     "Stateless, no cross-tool calls.”",
        "related_defect": None,
        "description": "A tool that calls another tool directly, or keeps mutable state, violates this invariant.",
        "alternative": "Move the shared logic into a data/intelligence-layer function both tools call, rather than one tool calling another.",
        "intent_pattern": re.compile(
            r"\b(tool|function)\s+(that\s+)?calls?\s+(another|other)\s+tool\b|"
            r"\bstateful\s+tool\b|\bglobal\s+state\s+in\s+(a\s+)?tool\b", re.IGNORECASE,
        ),
        "topic_pattern": re.compile(r"\binterface/tools\b|\btool\b", re.IGNORECASE),
    },
    {
        "name": "storage_under_cognirepo",
        "citation": "CLAUDE.md — “All storage lives under .cognirepo/ in the project root” "
                     "(with documented exceptions: cross-agent handoff, org graph, insights reports).",
        "related_defect": None,
        "description": "Writing persistent state outside .cognirepo/ (without it being one of the documented exceptions) violates this invariant.",
        "alternative": "Store under .cognirepo/ — or if this is a cross-agent handoff / org-graph / insights-report case, check CLAUDE.md's documented exceptions first.",
        "intent_pattern": re.compile(
            r"\b(store|write|save|persist)\w*\s+.{0,40}\b(outside|not\s+under|elsewhere\s+than)\s+\.cognirepo\b",
            re.IGNORECASE,
        ),
        "topic_pattern": re.compile(r".", re.IGNORECASE),  # intent_pattern alone is specific enough
    },
]

# ── decision contradiction check ────────────────────────────────────────────────
# Deliberately narrow: only even search past decisions when the instruction itself signals a
# reversal/replacement. An ordinary request never reaches the BM25 search at all — the
# strongest available guard against false positives on routine asks (AC2).
_REVERSAL_CUES = re.compile(
    r"\b(instead\s+of|instead|replace\w*|switch\s+(?:away\s+from|to)|stop\s+using|remove\w*|"
    r"drop\w*|avoid\w*|don\'?t\s+use|do\s+not\s+use|no\s+longer\s+use|abandon\w*|"
    r"migrate\s+(?:away\s+)?from)\b",
    re.IGNORECASE,
)


def _check_invariants(instruction: str) -> list[dict]:
    conflicts = []
    for inv in _INVARIANTS:
        if inv["intent_pattern"].search(instruction) and inv["topic_pattern"].search(instruction):
            conflicts.append({
                "type": "invariant",
                "name": inv["name"],
                "citation": inv["citation"],
                "related_defect": inv["related_defect"],
                "description": inv["description"],
                "suggested_alternative": inv["alternative"],
            })
    return conflicts


def _check_decisions(instruction: str) -> list[dict]:
    if not _REVERSAL_CUES.search(instruction):
        return []

    from data.memory.episodic_memory import _load, _build_bm25, _tokenize  # pylint: disable=import-outside-toplevel

    data = _load()
    decisions = [e for e in data if (e.get("metadata") or {}).get("type") == "decision"]
    if not decisions:
        return []

    bm25, event_ids = _build_bm25(decisions)
    if bm25 is None:
        return []

    tokens = _tokenize(instruction)
    if not tokens:
        return []

    scores = bm25.get_scores(tokens)
    best_pos = max(range(len(scores)), key=lambda i: scores[i])
    if scores[best_pos] <= 0:
        return []

    matched = decisions[best_pos]
    summary = (matched.get("metadata") or {}).get("summary") or matched.get("event", "")
    return [{
        "type": "decision",
        "episode_id": matched.get("id"),
        "citation": f"record_decision id={matched.get('id')}: {summary[:200]}",
        "description": (
            "This instruction contains a reversal/replacement cue and closely matches a "
            "previously recorded decision — confirm this is an intentional supersession, "
            "not an accidental contradiction."
        ),
        "suggested_alternative": (
            "If this is intentional, record the new decision (and consider "
            "supersede_learning on the old one) so the precedent stays current; if not, "
            "the original decision's rationale may still apply."
        ),
    }]


def check_precedent(instruction: str) -> dict:
    """
    Check `instruction` against recorded decisions and CLAUDE.md invariants before it's
    implemented. ALWAYS advisory — never blocks, never raises on a conflict; a human/agent
    still makes the final call (skill.md §F Gate 1/Gate 2 model).

    Returns: {"conflicts": [...], "advisory": True}
    `conflicts` is empty (not omitted) when there's nothing to flag — explicit "checked,
    found nothing" rather than silence, so a caller can distinguish "not checked" from
    "checked, clean".
    """
    conflicts: list[dict] = []
    conflicts.extend(_check_invariants(instruction))
    try:
        conflicts.extend(_check_decisions(instruction))
    except Exception:  # pylint: disable=broad-except
        pass  # a broken decision search must never block the (always-advisory) check itself
    return {"conflicts": conflicts, "advisory": True}
