"""
tests/test_mcp_server.py — MCP tool function unit tests.

We call the underlying tool functions directly (not through MCP transport)
since the MCP server runs over stdio and can't be unit-tested as a process.
"""
from __future__ import annotations

import json
import os

import pytest


class TestMCPToolFunctions:
    def test_store_memory_tool(self):
        from tools.store_memory import store_memory
        result = store_memory("test memory about JWT authentication", source="mcp_test")
        assert result["status"] == "stored"
        assert "importance" in result
        assert result["text"] == "test memory about JWT authentication"

    def test_retrieve_memory_tool_returns_list(self):
        from tools.store_memory import store_memory
        from tools.retrieve_memory import retrieve_memory
        store_memory("cached result for auth query in session")
        results = retrieve_memory("auth session", top_k=1)
        assert isinstance(results, list)

    def test_retrieve_memory_empty_store(self):
        from tools.retrieve_memory import retrieve_memory
        results = retrieve_memory("anything", top_k=5)
        assert isinstance(results, list)

    def test_log_episode_tool(self):
        from memory.episodic_memory import log_event, get_history
        log_event("mcp tool called: store_memory", {"source": "mcp"})
        history = get_history(1)
        assert len(history) >= 1
        assert "store_memory" in history[0]["event"]

    def test_manifest_written(self):
        import importlib.util
        from server.mcp_server import _write_manifest, _build_manifest
        _write_manifest()
        # manifest.json is written next to mcp_server.py (not CWD)
        import server.mcp_server as _mod
        manifest_path = os.path.join(os.path.dirname(_mod.__file__), "manifest.json")
        assert os.path.exists(manifest_path)
        data = _build_manifest()
        tool_names = [t["name"] for t in data.get("tools", [])]
        assert "store_memory" in tool_names
        assert "retrieve_memory" in tool_names
        assert "search_docs" in tool_names
        assert "log_episode" in tool_names

    def test_store_memory_importance_non_negative(self):
        from tools.store_memory import store_memory
        result = store_memory("short text")
        assert result["importance"] >= 0

    def test_store_memory_source_preserved(self):
        from tools.store_memory import store_memory
        result = store_memory("text with source", source="copilot")
        assert result.get("source") == "copilot"


class TestManifestFormat:
    def test_manifest_tools_have_required_fields(self):
        from server.mcp_server import _build_manifest
        manifest = _build_manifest()
        for tool in manifest.get("tools", []):
            assert "name" in tool
            assert "description" in tool

    def test_openai_spec_export(self):
        from server.mcp_server import _write_manifest
        _write_manifest()
        from adapters.openai_spec import export
        # _write_manifest writes next to mcp_server.py; openai_spec reads from there
        import server.mcp_server as _mod
        import adapters.openai_spec as _spec
        orig = _spec.MANIFEST_PATH
        import os
        _spec.MANIFEST_PATH = os.path.join(os.path.dirname(_mod.__file__), "manifest.json")
        try:
            paths = export(out_dir="adapters")
        finally:
            _spec.MANIFEST_PATH = orig
        assert os.path.exists(paths["openai_tools"])
        with open(paths["openai_tools"]) as f:
            tools = json.load(f)
        assert isinstance(tools, list)
        assert all(t["type"] == "function" for t in tools)
