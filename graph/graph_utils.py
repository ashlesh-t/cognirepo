# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Utility functions for the CogniRepo knowledge graph.
No imports from graph/ — safe to import anywhere.
"""
import re


# ── entity extraction ─────────────────────────────────────────────────────────

_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_FILE_EXT = re.compile(r"\b\w[\w/]*\.\w{1,6}\b")


def extract_entities_from_text(text: str) -> list[str]:
    """
    Lightweight rule-based entity extractor — no NER model.

    Pulls:
    - CamelCase tokens (class / type names)
    - snake_case tokens with at least one underscore
    - file-path-like tokens ending with a known extension (.py, .md, .ts, …)

    Returns a deduplicated list of candidate entity strings.
    """
    entities: list[str] = []
    seen: set[str] = set()

    for token in re.split(r"[\s,;:()\[\]{}'\"]+", text):
        token = token.strip(".")
        if not token or len(token) < 2:
            continue

        candidates = []

        # file-path-like  (auth.py, retrieval/hybrid.py)
        if _FILE_EXT.match(token):
            candidates.append(token)

        # snake_case  (verify_token, store_memory)
        if "_" in token and token.replace("_", "").isalpha():
            candidates.append(token)

        # CamelCase  (AuthHandler, LocalVectorDB)
        if re.search(r"[A-Z]", token) and re.search(r"[a-z]", token):
            candidates.append(token)
            # also add individual words split out of camelCase
            words = _CAMEL.sub("_", token).lower().split("_")
            candidates.extend(w for w in words if len(w) > 2)

        for c in candidates:
            if c not in seen:
                seen.add(c)
                entities.append(c)

    return entities


# ── node ID construction ──────────────────────────────────────────────────────

def make_node_id(entity_type: str, name: str, file: str | None = None) -> str:
    """
    Deterministic node ID generator.

    | entity_type        | result example                        |
    |--------------------|---------------------------------------|
    | FILE               | "auth/auth.py"                        |
    | FUNCTION / CLASS   | "auth/auth.py::verify_token"          |
    | CONCEPT            | "concept::jwt_auth"                   |
    | QUERY              | "q_<name>" (caller supplies uuid hex) |
    | SESSION            | "s_<name>"                            |
    | USER_ACTION        | "action_<name>"                       |
    """
    etype = entity_type.upper()
    if etype == "FILE":
        return name
    if etype in ("FUNCTION", "CLASS"):
        if file:
            return f"{file}::{name}"
        return f"symbol::{name}"
    if etype == "CONCEPT":
        return f"concept::{name.lower()}"
    if etype == "QUERY":
        return f"q_{name}"
    if etype == "SESSION":
        return f"s_{name}"
    if etype == "USER_ACTION":
        return f"action_{name}"
    return f"{etype.lower()}::{name}"


def node_id_from_symbol_record(symbol: dict, file_path: str) -> str:
    """
    Convenience wrapper for ASTIndexer symbol records.
    symbol = {"name": "verify_token", "type": "FUNCTION", ...}
    """
    return make_node_id(symbol["type"], symbol["name"], file_path)


# ── subgraph formatting ───────────────────────────────────────────────────────

def format_subgraph_for_context(subgraph: dict) -> str:
    """
    Convert {"nodes": [...], "edges": [...]} to a compact string
    suitable for injection into an LLM context window.
    """
    lines: list[str] = []

    nodes = subgraph.get("nodes", [])
    edges = subgraph.get("edges", [])

    if nodes:
        lines.append("Graph nodes:")
        for n in nodes:
            node_id = n.get("node_id", "?")
            ntype = n.get("type", "?")
            hops = n.get("hops")
            hop_str = f"  ({hops} hop{'s' if hops != 1 else ''} away)" if hops is not None else ""
            lines.append(f"  {node_id} [{ntype}]{hop_str}")

    if edges:
        lines.append("Relationships:")
        for e in edges:
            lines.append(f"  {e.get('src')} --{e.get('rel')}--> {e.get('dst')}")

    return "\n".join(lines) if lines else "(empty graph)"
