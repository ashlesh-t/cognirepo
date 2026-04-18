# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_tool_first_workflow.py — Sprint 6 / TASK-017 acceptance tests.

Covers:
  - .claude/CLAUDE.md exists and contains "TOOL-FIRST WORKFLOW" section
  - .claude/CLAUDE.md lists MANDATORY rules (context_pack, lookup_symbol, who_calls, subgraph)
  - .claude/CLAUDE.md lists NEVER rules (no raw file read, assume location, skip search)
  - .gemini/COGNIREPO.md exists with equivalent Gemini CLI instructions
  - Both files emphasize semantic search and context_pack before any file reads
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


class TestClaudeMDToolFirst:
    def test_claude_md_exists(self):
        """CLAUDE.md must exist in .claude/ directory."""
        claude_file = REPO_ROOT / ".claude" / "CLAUDE.md"
        assert claude_file.exists(), ".claude/CLAUDE.md is missing"

    def test_claude_md_contains_tool_first_section(self):
        """CLAUDE.md must explicitly state TOOL-FIRST WORKFLOW."""
        content = (REPO_ROOT / ".claude" / "CLAUDE.md").read_text()
        assert "TOOL-FIRST WORKFLOW" in content or "tool-first" in content.lower(), (
            "CLAUDE.md must emphasize tool-first workflow"
        )

    def test_claude_md_lists_mandatory_rules(self):
        """CLAUDE.md must clearly list MANDATORY tool usage rules."""
        content = (REPO_ROOT / ".claude" / "CLAUDE.md").read_text()
        mandatory_keywords = ["MANDATORY", "context_pack", "lookup_symbol", "who_calls", "subgraph"]
        missing = [kw for kw in mandatory_keywords if kw not in content]
        assert not missing, f"CLAUDE.md missing mandatory keywords: {missing}"

    def test_claude_md_lists_never_rules(self):
        """CLAUDE.md must list NEVER rules (no raw reads, no assumptions, no skip)."""
        content = (REPO_ROOT / ".claude" / "CLAUDE.md").read_text()
        never_keywords = ["NEVER", "read_file", "assume", "skip"]
        assert "NEVER" in content, "CLAUDE.md must have 'NEVER' section"

    def test_claude_md_context_pack_before_file_read(self):
        """CLAUDE.md must state context_pack MUST be called before reading files."""
        content = (REPO_ROOT / ".claude" / "CLAUDE.md").read_text()
        assert "context_pack" in content and ("before" in content or "first" in content), (
            "CLAUDE.md must emphasize context_pack before file reads"
        )

    def test_claude_md_recommends_retrieve_memory(self):
        """CLAUDE.md should mention retrieve_memory for prior decisions."""
        content = (REPO_ROOT / ".claude" / "CLAUDE.md").read_text()
        assert "retrieve_memory" in content or "semantic" in content.lower(), (
            "CLAUDE.md should guide semantic memory lookups"
        )

    def test_claude_md_recommends_search_docs(self):
        """CLAUDE.md should mention search_docs for documentation."""
        content = (REPO_ROOT / ".claude" / "CLAUDE.md").read_text()
        assert "search_docs" in content or "documentation" in content.lower(), (
            "CLAUDE.md should guide documentation searches"
        )


class TestGeminiCOGNIREPOMD:
    def test_gemini_cognirepo_md_exists(self):
        """.gemini/COGNIREPO.md must exist with Gemini CLI instructions."""
        gemini_file = REPO_ROOT / ".gemini" / "COGNIREPO.md"
        assert gemini_file.exists(), ".gemini/COGNIREPO.md is missing"

    def test_gemini_cognirepo_md_contains_tool_first_section(self):
        """Gemini COGNIREPO.md must emphasize TOOL-FIRST WORKFLOW."""
        content = (REPO_ROOT / ".gemini" / "COGNIREPO.md").read_text()
        assert "TOOL-FIRST WORKFLOW" in content or "tool-first" in content.lower(), (
            "Gemini COGNIREPO.md must emphasize tool-first workflow"
        )

    def test_gemini_cognirepo_md_lists_mcp_tools(self):
        """Gemini COGNIREPO.md must list available MCP tools."""
        content = (REPO_ROOT / ".gemini" / "COGNIREPO.md").read_text()
        tool_keywords = ["context_pack", "lookup_symbol", "who_calls", "subgraph"]
        missing = [t for t in tool_keywords if t not in content]
        assert not missing, f"Gemini COGNIREPO.md missing tools: {missing}"

    def test_gemini_cognirepo_md_lists_mandatory_rules(self):
        """Gemini COGNIREPO.md must clearly state MANDATORY rules."""
        content = (REPO_ROOT / ".gemini" / "COGNIREPO.md").read_text()
        assert "MANDATORY" in content, "Gemini COGNIREPO.md must state MANDATORY rules"

    def test_gemini_cognirepo_md_lists_never_rules(self):
        """Gemini COGNIREPO.md must list NEVER rules."""
        content = (REPO_ROOT / ".gemini" / "COGNIREPO.md").read_text()
        assert "NEVER" in content, "Gemini COGNIREPO.md must have 'NEVER' section"

    def test_gemini_cognirepo_md_context_pack_emphasis(self):
        """Gemini COGNIREPO.md must emphasize context_pack before file reads."""
        content = (REPO_ROOT / ".gemini" / "COGNIREPO.md").read_text()
        assert "context_pack" in content, "Gemini COGNIREPO.md must mention context_pack"
        assert "before" in content.lower() or "first" in content.lower(), (
            "Gemini COGNIREPO.md must emphasize calling context_pack first"
        )


class TestToolFirstWorkflowDocumentation:
    def test_both_files_mention_context_pack(self):
        """Both .claude/CLAUDE.md and .gemini/COGNIREPO.md must mention context_pack."""
        claude_content = (REPO_ROOT / ".claude" / "CLAUDE.md").read_text()
        gemini_content = (REPO_ROOT / ".gemini" / "COGNIREPO.md").read_text()
        assert "context_pack" in claude_content
        assert "context_pack" in gemini_content

    def test_both_files_mention_lookup_symbol(self):
        """Both files must mention lookup_symbol for locating functions."""
        claude_content = (REPO_ROOT / ".claude" / "CLAUDE.md").read_text()
        gemini_content = (REPO_ROOT / ".gemini" / "COGNIREPO.md").read_text()
        assert "lookup_symbol" in claude_content
        assert "lookup_symbol" in gemini_content

    def test_both_files_mention_who_calls(self):
        """Both files must mention who_calls for impact analysis."""
        claude_content = (REPO_ROOT / ".claude" / "CLAUDE.md").read_text()
        gemini_content = (REPO_ROOT / ".gemini" / "COGNIREPO.md").read_text()
        assert "who_calls" in claude_content
        assert "who_calls" in gemini_content

    def test_both_files_mention_subgraph(self):
        """Both files must mention subgraph for architecture questions."""
        claude_content = (REPO_ROOT / ".claude" / "CLAUDE.md").read_text()
        gemini_content = (REPO_ROOT / ".gemini" / "COGNIREPO.md").read_text()
        assert "subgraph" in claude_content
        assert "subgraph" in gemini_content

    def test_both_files_forbid_raw_file_reads(self):
        """Both files must forbid raw file reads without context_pack."""
        claude_content = (REPO_ROOT / ".claude" / "CLAUDE.md").read_text()
        gemini_content = (REPO_ROOT / ".gemini" / "COGNIREPO.md").read_text()
        assert "read_file" in claude_content or "raw" in claude_content.lower()
        assert "read_file" in gemini_content or "raw" in gemini_content.lower()

    def test_both_files_forbid_assumptions(self):
        """Both files must forbid assuming code location."""
        claude_content = (REPO_ROOT / ".claude" / "CLAUDE.md").read_text()
        gemini_content = (REPO_ROOT / ".gemini" / "COGNIREPO.md").read_text()
        assert "assume" in claude_content.lower()
        assert "assume" in gemini_content.lower()
