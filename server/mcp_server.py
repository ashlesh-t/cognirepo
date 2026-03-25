"""
Real MCP server for CogniRepo — stdio transport, works with Claude Desktop
and any stdio MCP client.
"""
import json
import os
from mcp.server.fastmcp import FastMCP

from tools.store_memory import store_memory as _store_memory
from tools.retrieve_memory import retrieve_memory as _retrieve_memory
from retrieval.docs_search import search_docs as _search_docs
from memory.episodic_memory import log_event

mcp = FastMCP("cognirepo")


@mcp.tool()
def store_memory(text: str, source: str = "") -> dict:
    """Store a semantic memory with an optional source label."""
    return _store_memory(text, source)


@mcp.tool()
def retrieve_memory(query: str, top_k: int = 5) -> list:
    """Retrieve the top-k memories most similar to the query."""
    return _retrieve_memory(query, top_k)


@mcp.tool()
def search_docs(query: str) -> list:
    """Search all markdown documentation files for the given query string."""
    return _search_docs(query)


@mcp.tool()
def log_episode(event: str, metadata: dict = None) -> dict:
    """Append an episodic event with optional metadata to the event log."""
    log_event(event, metadata or {})
    return {"status": "logged", "event": event}


def _build_manifest() -> dict:
    """Return the tool-schema manifest so non-MCP clients can read it."""
    return {
        "name": "cognirepo",
        "version": "0.1.0",
        "transport": "stdio",
        "tools": [
            {
                "name": "store_memory",
                "description": "Store a semantic memory with an optional source label.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text":   {"type": "string", "description": "Memory text to store"},
                        "source": {"type": "string", "description": "Origin label (file, url, …)", "default": ""},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "retrieve_memory",
                "description": "Retrieve the top-k memories most similar to the query.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "top_k": {"type": "integer", "description": "Number of results", "default": 5},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "search_docs",
                "description": "Search all markdown documentation files for the given query string.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Text to search for in .md files"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "log_episode",
                "description": "Append an episodic event with optional metadata to the event log.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "event":    {"type": "string", "description": "Event description"},
                        "metadata": {"type": "object", "description": "Arbitrary key-value metadata", "default": {}},
                    },
                    "required": ["event"],
                },
            },
        ],
    }


def _write_manifest() -> None:
    manifest_path = os.path.join(os.path.dirname(__file__), "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(_build_manifest(), f, indent=2)


def run_server() -> None:
    """Entry point called by the CLI — writes manifest then starts stdio MCP server."""
    _write_manifest()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
