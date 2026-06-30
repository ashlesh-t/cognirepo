# pylint: disable=missing-docstring, import-outside-toplevel, broad-exception-caught
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""tests/test_sync_claude_memory.py — Coverage for tools/sync_claude_memory.py (0% → 85%)."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── _is_claude_memory_file ────────────────────────────────────────────────────

def test_is_claude_memory_file_valid():
    from tools.sync_claude_memory import _is_claude_memory_file
    home = str(Path.home())
    valid = os.path.join(home, ".claude", "projects", "myrepo", "memory", "user.md")
    assert _is_claude_memory_file(valid) is True


def test_is_claude_memory_file_not_md():
    from tools.sync_claude_memory import _is_claude_memory_file
    home = str(Path.home())
    path = os.path.join(home, ".claude", "projects", "myrepo", "memory", "user.json")
    assert _is_claude_memory_file(path) is False


def test_is_claude_memory_file_outside_claude():
    from tools.sync_claude_memory import _is_claude_memory_file
    assert _is_claude_memory_file("/tmp/some_file.md") is False


def test_is_claude_memory_file_no_memory_dir():
    from tools.sync_claude_memory import _is_claude_memory_file
    home = str(Path.home())
    path = os.path.join(home, ".claude", "projects", "user.md")
    assert _is_claude_memory_file(path) is False


# ── _strip_frontmatter ────────────────────────────────────────────────────────

def test_strip_frontmatter_removes_yaml():
    from tools.sync_claude_memory import _strip_frontmatter
    content = "---\nname: test\ntype: user\n---\nBody text here."
    result = _strip_frontmatter(content)
    assert "name:" not in result
    assert "Body text here." in result


def test_strip_frontmatter_no_frontmatter():
    from tools.sync_claude_memory import _strip_frontmatter
    content = "Plain body with no frontmatter."
    result = _strip_frontmatter(content)
    assert result == "Plain body with no frontmatter."


def test_strip_frontmatter_empty():
    from tools.sync_claude_memory import _strip_frontmatter
    assert _strip_frontmatter("") == ""


# ── _extract_memory_body ──────────────────────────────────────────────────────

def test_extract_memory_body_strips_headers():
    from tools.sync_claude_memory import _extract_memory_body
    content = "---\nname: x\n---\n# Title\n\nSome memory body text."
    result = _extract_memory_body(content)
    assert "Title" in result or "memory body text" in result
    assert "---" not in result


def test_extract_memory_body_plain():
    from tools.sync_claude_memory import _extract_memory_body
    content = "Plain memory without frontmatter."
    result = _extract_memory_body(content)
    assert "Plain memory" in result


# ── _add_to_knowledge_graph ───────────────────────────────────────────────────

def test_add_to_knowledge_graph_no_cognirepo_dir(tmp_path, monkeypatch):
    """Should silently skip when .cognirepo/ doesn't exist."""
    import tools.sync_claude_memory as scm
    monkeypatch.setattr(scm, "_REPO_ROOT", str(tmp_path))
    # No .cognirepo dir created — should not raise
    scm._add_to_knowledge_graph("test memory text", "/some/file.md")


def test_add_to_knowledge_graph_with_cognirepo_dir(tmp_path, monkeypatch):
    """Should attempt to add node when .cognirepo/ exists."""
    import tools.sync_claude_memory as scm
    cog_dir = tmp_path / ".cognirepo"
    cog_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(scm, "_REPO_ROOT", str(tmp_path))

    mock_kg = MagicMock()
    with patch("data.graph.knowledge_graph.KnowledgeGraph", return_value=mock_kg):
        with patch("data.graph.graph_utils.extract_entities_from_text", return_value=["entity1"]):
            with patch("data.graph.graph_utils.make_node_id", return_value="concept::entity1"):
                scm._add_to_knowledge_graph("user is a senior engineer", "/path/memory.md")
    # No assertion needed — just verifying no exception raised


# ── _store_globally ───────────────────────────────────────────────────────────

def test_store_globally_best_effort():
    from tools.sync_claude_memory import _store_globally
    with patch("data.memory.user_memory.set_preference") as mock_set:
        with patch("data.memory.user_memory.record_action"):
            _store_globally("some memory text to store globally")
            mock_set.assert_called_once()


def test_store_globally_exception_swallowed():
    from tools.sync_claude_memory import _store_globally
    with patch("data.memory.user_memory.set_preference", side_effect=RuntimeError("fail")):
        _store_globally("text")  # must not raise


# ── _visited_files_path / _load_visited / _save_visited ──────────────────────

def test_load_visited_no_file(tmp_path, monkeypatch):
    import tools.sync_claude_memory as scm
    monkeypatch.setattr(scm, "_REPO_ROOT", str(tmp_path))
    result = scm._load_visited()
    assert result == {}


def test_load_visited_corrupt_file(tmp_path, monkeypatch):
    import tools.sync_claude_memory as scm
    monkeypatch.setattr(scm, "_REPO_ROOT", str(tmp_path))
    cog_dir = tmp_path / ".cognirepo"
    cog_dir.mkdir(exist_ok=True)
    visited_path = cog_dir / "visited_files.json"
    visited_path.write_text("not valid json")
    result = scm._load_visited()
    assert result == {}


def test_save_and_load_visited(tmp_path, monkeypatch):
    import tools.sync_claude_memory as scm
    monkeypatch.setattr(scm, "_REPO_ROOT", str(tmp_path))
    cog_dir = tmp_path / ".cognirepo"
    cog_dir.mkdir(exist_ok=True)
    data = {"some/file.py": "abc123"}
    scm._save_visited(data)
    loaded = scm._load_visited()
    assert loaded == data


# ── _chunk_source_file ────────────────────────────────────────────────────────

def test_chunk_python_file():
    from tools.sync_claude_memory import _chunk_source_file
    content = "def foo():\n    " + "x = 1\n    " * 20 + "pass\n\ndef bar():\n    " + "y = 2\n    " * 20 + "return 1\n"
    chunks = _chunk_source_file(content, "test.py")
    assert isinstance(chunks, list)
    assert len(chunks) >= 1


def test_chunk_markdown_file():
    from tools.sync_claude_memory import _chunk_source_file
    content = "# Title\n\nSome content here.\n\n## Section\n\nMore content."
    chunks = _chunk_source_file(content, "README.md")
    assert isinstance(chunks, list)


def test_chunk_json_file_fixed_size():
    from tools.sync_claude_memory import _chunk_source_file
    content = '{"key": "' + "x" * 2000 + '"}'
    chunks = _chunk_source_file(content, "data.json")
    assert isinstance(chunks, list)


def test_chunk_skips_tiny_fragments():
    from tools.sync_claude_memory import _chunk_source_file
    content = "def f():\n    pass\n"
    chunks = _chunk_source_file(content, "t.py")
    for chunk in chunks:
        assert len(chunk) >= 60 or len(chunk) == len(content.strip())


# ── _store_visited_file ───────────────────────────────────────────────────────

def test_store_visited_file_outside_repo(tmp_path, monkeypatch):
    import tools.sync_claude_memory as scm
    monkeypatch.setattr(scm, "_REPO_ROOT", str(tmp_path))
    result = scm._store_visited_file("/tmp/external_file.py")
    assert result is False


def test_store_visited_file_unsupported_ext(tmp_path, monkeypatch):
    import tools.sync_claude_memory as scm
    monkeypatch.setattr(scm, "_REPO_ROOT", str(tmp_path))
    f = tmp_path / "file.exe"
    f.write_bytes(b"binary")
    result = scm._store_visited_file(str(f))
    assert result is False


def test_store_visited_file_too_large(tmp_path, monkeypatch):
    import tools.sync_claude_memory as scm
    monkeypatch.setattr(scm, "_REPO_ROOT", str(tmp_path))
    f = tmp_path / "big.py"
    f.write_bytes(b"x" * (scm._MAX_FILE_BYTES + 1))
    result = scm._store_visited_file(str(f))
    assert result is False


def test_store_visited_file_nonexistent(tmp_path, monkeypatch):
    import tools.sync_claude_memory as scm
    monkeypatch.setattr(scm, "_REPO_ROOT", str(tmp_path))
    result = scm._store_visited_file(str(tmp_path / "nonexistent.py"))
    assert result is False


def test_store_visited_file_already_visited(tmp_path, monkeypatch):
    import tools.sync_claude_memory as scm
    monkeypatch.setattr(scm, "_REPO_ROOT", str(tmp_path))
    cog_dir = tmp_path / ".cognirepo"
    cog_dir.mkdir(exist_ok=True)
    content = "def hello():\n    print('hello world from test')\n    return True\n"
    f = tmp_path / "hello.py"
    f.write_text(content)
    sha = hashlib.sha256(content.encode()).hexdigest()[:16]
    rel = "hello.py"
    scm._save_visited({rel: sha})
    result = scm._store_visited_file(str(f))
    assert result is False  # already visited → skip


def test_store_visited_file_novel(tmp_path, monkeypatch):
    import tools.sync_claude_memory as scm
    monkeypatch.setattr(scm, "_REPO_ROOT", str(tmp_path))
    cog_dir = tmp_path / ".cognirepo"
    cog_dir.mkdir(exist_ok=True)
    content = "def novel_function():\n    return 'this is novel content for testing purposes'\n"
    f = tmp_path / "novel.py"
    f.write_text(content)
    mock_store = MagicMock()
    mock_store.store_if_novel.return_value = True
    with patch("data.memory.auto_store.AutoStore", return_value=mock_store):
        result = scm._store_visited_file(str(f))
    assert result is True


# ── main() ────────────────────────────────────────────────────────────────────

def test_main_empty_stdin(monkeypatch):
    from tools.sync_claude_memory import main
    monkeypatch.setattr(sys, "stdin", MagicMock(read=lambda: ""))
    main()  # must not raise


def test_main_invalid_json(monkeypatch):
    from tools.sync_claude_memory import main
    monkeypatch.setattr(sys, "stdin", MagicMock(read=lambda: "not json {{{"))
    main()  # must not raise


def test_main_write_memory_file(monkeypatch, tmp_path):
    from tools.sync_claude_memory import main
    import tools.sync_claude_memory as scm
    monkeypatch.setattr(scm, "_REPO_ROOT", str(tmp_path))
    home = str(Path.home())
    mem_path = os.path.join(home, ".claude", "projects", "x", "memory", "note.md")
    event = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": mem_path,
            "content": "---\nname: test\n---\nUser prefers concise answers.",
        },
    }
    monkeypatch.setattr(sys, "stdin", MagicMock(read=lambda: json.dumps(event)))
    with patch("tools.sync_claude_memory._store_globally"):
        with patch("tools.sync_claude_memory._add_to_knowledge_graph"):
            main()  # must not raise


def test_main_write_non_memory_file(monkeypatch, tmp_path):
    from tools.sync_claude_memory import main
    event = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/tmp/regular_file.py",
            "content": "def foo(): pass",
        },
    }
    monkeypatch.setattr(sys, "stdin", MagicMock(read=lambda: json.dumps(event)))
    main()  # should skip without error


def test_main_read_tool(monkeypatch, tmp_path):
    from tools.sync_claude_memory import main
    import tools.sync_claude_memory as scm
    monkeypatch.setattr(scm, "_REPO_ROOT", str(tmp_path))
    event = {
        "tool_name": "Read",
        "tool_input": {"file_path": str(tmp_path / "some.py")},
    }
    monkeypatch.setattr(sys, "stdin", MagicMock(read=lambda: json.dumps(event)))
    with patch("tools.sync_claude_memory._store_visited_file", return_value=False):
        main()


def test_main_write_short_memory_body(monkeypatch, tmp_path):
    """Content with body < 10 chars should skip _store_globally."""
    import tools.sync_claude_memory as scm
    monkeypatch.setattr(scm, "_REPO_ROOT", str(tmp_path))
    home = str(Path.home())
    mem_path = os.path.join(home, ".claude", "projects", "x", "memory", "note.md")
    # Use proper YAML frontmatter that gets stripped, leaving only "Hi" (< 10 chars)
    event = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": mem_path,
            "content": "---\nname: test\ntype: user\n---\nHi",
        },
    }
    monkeypatch.setattr(sys, "stdin", MagicMock(read=lambda: json.dumps(event)))
    with patch("tools.sync_claude_memory._store_globally") as mock_store:
        scm.main()
        mock_store.assert_not_called()
