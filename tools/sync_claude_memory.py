# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-it/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Claude Code PostToolUse hook — syncs auto-memory writes to CogniRepo.

Called by Claude Code after every Write tool use. Reads the hook event from
stdin (JSON), then:
  1. Checks if the written file is a Claude memory file
     (~/.claude/projects/*/memory/*.md)
  2. Strips YAML frontmatter and extracts the memory body
  3. Stores it in the global ~/.cognirepo/ FAISS index
  4. Adds a MEMORY node + concept edges to the project knowledge graph
     so Gemini / Cursor / any MCP client can discover it via subgraph()

Usage (set in .claude/settings.json hooks):
  python /path/to/cognirepo/tools/sync_claude_memory.py
"""
import json
import os
import re
import sys
from pathlib import Path

# Set repo root in sys.path and CWD immediately so all cognirepo imports resolve
# correctly regardless of what CWD Claude Code inherits when firing the hook.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
os.chdir(_REPO_ROOT)


# ── helpers ───────────────────────────────────────────────────────────────────

def _is_claude_memory_file(file_path: str) -> bool:
    """True when the written path is under ~/.claude/.../memory/"""
    home = str(Path.home())
    norm = os.path.normpath(file_path)
    claude_mem = os.path.join(home, ".claude")
    return norm.startswith(claude_mem) and "/memory/" in norm and norm.endswith(".md")


def _strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter (--- ... ---) and return the body."""
    stripped = re.sub(r"^---\n.*?\n---\n?", "", content, flags=re.DOTALL)
    return stripped.strip()


def _extract_memory_body(content: str) -> str:
    """Return meaningful text: strip frontmatter, collapse whitespace."""
    body = _strip_frontmatter(content)
    # Remove markdown headers and blank lines
    lines = [ln.lstrip("#").strip() for ln in body.splitlines() if ln.strip()]
    return " ".join(lines)


# ── knowledge graph sync ──────────────────────────────────────────────────────

def _add_to_knowledge_graph(text: str, source_file: str) -> None:
    """
    Add a MEMORY node to the project KG and link it to extracted concepts.

    Node  :  memory::<8-char hash>   type=MEMORY
    Edges :  MEMORY → CONCEPT  (RELATES_TO) for each entity in the text
    """
    try:
        cognirepo_dir = os.path.join(_REPO_ROOT, ".cognirepo")
        if not os.path.isdir(cognirepo_dir):
            return

        import hashlib  # pylint: disable=import-outside-toplevel
        from graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType  # pylint: disable=import-outside-toplevel
        from graph.graph_utils import extract_entities_from_text, make_node_id  # pylint: disable=import-outside-toplevel

        node_hash = hashlib.sha256(text.encode()).hexdigest()[:8]
        node_id = f"memory::{node_hash}"

        kg = KnowledgeGraph()
        kg.add_node(
            node_id,
            node_type="MEMORY",
            text=text[:200],
            source=os.path.basename(source_file),
            agent="claude",
            scope="global",
        )

        # Link to concepts extracted from the memory text
        entities = extract_entities_from_text(text)
        for entity in entities:
            concept_id = make_node_id(NodeType.CONCEPT, entity)
            kg.add_node(concept_id, node_type=NodeType.CONCEPT, label=entity)
            kg.add_edge(node_id, concept_id, EdgeType.RELATES_TO, weight=0.8)

        kg.save()
    except Exception:  # pylint: disable=broad-except
        pass  # KG sync is best-effort — never block the memory write


# ── global FAISS store sync ───────────────────────────────────────────────────

def _store_globally(text: str) -> None:
    """Persist text in the global ~/.cognirepo/ user memory store."""
    try:
        from memory.user_memory import set_preference, record_action  # pylint: disable=import-outside-toplevel
        import hashlib  # pylint: disable=import-outside-toplevel
        key = f"memory:{hashlib.sha256(text.encode()).hexdigest()[:8]}"
        set_preference(key, {"text": text, "source": "claude-auto-memory", "agent": "claude"})
        record_action("claude-memory-sync")
    except Exception:  # pylint: disable=broad-except
        pass  # best-effort


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        event = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return

    # PostToolUse event structure: {"tool_name": "Write", "tool_input": {...}, ...}
    tool_name = event.get("tool_name", "")
    if tool_name != "Write":
        return

    tool_input = event.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    content   = tool_input.get("content", "")

    if not _is_claude_memory_file(file_path):
        return

    text = _extract_memory_body(content)
    if len(text) < 10:
        return

    _store_globally(text)
    _add_to_knowledge_graph(text, file_path)


if __name__ == "__main__":
    main()
