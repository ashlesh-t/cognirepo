# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-it/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

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

# ── visited-file cache ────────────────────────────────────────────────────────

# File extensions worth indexing when read as fallback
_CODE_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs",
    ".cpp", ".c", ".h", ".rb", ".php", ".cs", ".swift", ".kt",
    ".md", ".rst", ".txt", ".yaml", ".yml", ".toml", ".json",
})

# Skip files above this size (bytes) — large generated/vendored files
_MAX_FILE_BYTES = 50_000


def _visited_files_path() -> str:
    return os.path.join(_REPO_ROOT, ".cognirepo", "visited_files.json")


def _load_visited() -> dict[str, str]:
    """Load {rel_path: sha256} dedup store."""
    path = _visited_files_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_visited(visited: dict[str, str]) -> None:
    path = _visited_files_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(visited, f, indent=2)
    except OSError:
        pass


def _chunk_source_file(content: str, file_path: str) -> list[str]:
    """
    Split source file into semantic chunks (~800 chars each).
    Splits on class/function definition boundaries first, then by paragraph.
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext in (".py", ".js", ".ts", ".java", ".go", ".rs", ".rb"):
        # Split on top-level def/class/func boundaries
        parts = re.split(r"(?m)^(?=(?:def |class |func |function |public |private |protected ))", content)
    elif ext in (".md", ".rst", ".txt"):
        # Split on headings / blank lines
        parts = re.split(r"(?m)^(?=#{1,3} |\n{2,})", content)
    else:
        # Fixed-size chunks (~800 chars)
        parts = [content[i:i+800] for i in range(0, len(content), 800)]

    chunks = []
    for part in parts:
        part = part.strip()
        if len(part) >= 60:  # skip tiny fragments
            chunks.append(part[:1200])  # cap each chunk
    return chunks[:40]  # max 40 chunks per file


def _store_visited_file(file_path: str) -> bool:
    """
    Read a project source file, chunk it, and store novel chunks via AutoStore.
    Guards: project-dir only, code extensions only, size limit, sha256 dedup.
    Returns True if anything was stored.
    """
    # Guard: must be within _REPO_ROOT
    abs_path = os.path.abspath(file_path)
    if not abs_path.startswith(_REPO_ROOT):
        return False

    # Guard: supported extension
    ext = os.path.splitext(abs_path)[1].lower()
    if ext not in _CODE_EXTENSIONS:
        return False

    # Guard: file must exist
    if not os.path.isfile(abs_path):
        return False

    # Guard: size limit
    try:
        if os.path.getsize(abs_path) > _MAX_FILE_BYTES:
            return False
        content = Path(abs_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False

    # Guard: sha256 dedup — skip if file unchanged since last store
    import hashlib  # pylint: disable=import-outside-toplevel
    sha = hashlib.sha256(content.encode()).hexdigest()[:16]
    rel_path = os.path.relpath(abs_path, _REPO_ROOT)
    visited = _load_visited()
    if visited.get(rel_path) == sha:
        return False  # unchanged — already stored

    # Chunk and store
    try:
        from memory.auto_store import AutoStore  # pylint: disable=import-outside-toplevel
        store = AutoStore()
        chunks = _chunk_source_file(content, abs_path)
        stored_any = False
        for chunk in chunks:
            # Prefix with filename for better retrieval context
            text = f"[{rel_path}]\n{chunk}"
            if store.store_if_novel(text, source_tool="file_read", importance=0.5):
                stored_any = True
        if stored_any:
            visited[rel_path] = sha
            _save_visited(visited)
        return stored_any
    except Exception:  # pylint: disable=broad-except
        return False  # always best-effort


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        event = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return

    # PostToolUse event structure: {"tool_name": "...", "tool_input": {...}, ...}
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})

    # ── Write hook: sync Claude auto-memory files to CogniRepo ───────────────
    if tool_name == "Write":
        file_path = tool_input.get("file_path", "")
        content   = tool_input.get("content", "")
        if _is_claude_memory_file(file_path):
            text = _extract_memory_body(content)
            if len(text) >= 10:
                _store_globally(text)
                _add_to_knowledge_graph(text, file_path)
        return

    # ── Read hook: cache visited project source files for future retrieval ────
    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        if file_path:
            _store_visited_file(file_path)
        return


if __name__ == "__main__":
    main()
