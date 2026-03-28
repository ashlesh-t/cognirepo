# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
4A — OpenAI-Compatible Tool Spec Exporter

Reads server/manifest.json and writes two files:
  adapters/openai_tools.json       — OpenAI function-calling format
  adapters/cursor_mcp_config.json  — Cursor .cursor/mcp.json format

Usage
-----
    python -m adapters.openai_spec             # writes to adapters/
    python -m adapters.openai_spec --out-dir . # custom output dir
    from adapters.openai_spec import export    # programmatic
"""
from __future__ import annotations

import argparse
import json
import os
import sys

MANIFEST_PATH = "server/manifest.json"
DEFAULT_OUT_DIR = "adapters"
API_URL_FALLBACK = "http://localhost:8080"
GRPC_PORT_FALLBACK = 50051


def _load_manifest() -> list[dict]:
    if not os.path.exists(MANIFEST_PATH):
        print(f"[openai_spec] manifest not found at {MANIFEST_PATH}; generating…", file=sys.stderr)
        try:
            from server.mcp_server import _write_manifest  # pylint: disable=import-outside-toplevel
            _write_manifest()
        except Exception as exc:  # pylint: disable=broad-except
            print(f"[openai_spec] could not generate manifest: {exc}", file=sys.stderr)
            return []
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("tools", [])


def _load_config() -> dict:
    cfg_path = ".cognirepo/config.json"
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _to_openai_tool(entry: dict) -> dict:
    """Convert a CogniRepo manifest entry to an OpenAI function-calling tool."""
    parameters = entry.get("parameters", entry.get("inputSchema", {}))
    if not isinstance(parameters, dict):
        parameters = {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": entry["name"],
            "description": entry.get("description", ""),
            "parameters": parameters,
        },
    }


def _to_cursor_mcp_config(api_url: str, tools: list[dict]) -> dict:
    """
    Cursor supports .cursor/mcp.json — an MCP server definition.
    We expose CogniRepo as a stdio MCP server so Cursor can call
    store_memory / retrieve_memory / search_docs / log_episode natively.
    """
    return {
        "mcpServers": {
            "cognirepo": {
                "command": "cognirepo",
                "args": ["serve"],
                "env": {
                    "COGNIREPO_API_URL": api_url,
                },
            }
        },
        "_comment": (
            "Drop this file at .cursor/mcp.json in your project root. "
            "Restart Cursor. CogniRepo tools will appear in the tool selector."
        ),
        "_tools_preview": [t["function"]["name"] for t in tools],
    }


def export(out_dir: str = DEFAULT_OUT_DIR) -> dict[str, str]:
    """
    Export both JSON files.  Returns dict of {filename: path}.
    """
    os.makedirs(out_dir, exist_ok=True)
    cfg = _load_config()
    api_url = cfg.get("api_url", API_URL_FALLBACK)

    manifest = _load_manifest()
    if not manifest:
        print("[openai_spec] empty manifest — nothing to export", file=sys.stderr)
        return {}

    # ── openai_tools.json ─────────────────────────────────────────────────────
    openai_tools = [_to_openai_tool(e) for e in manifest]
    tools_path = os.path.join(out_dir, "openai_tools.json")
    with open(tools_path, "w", encoding="utf-8") as f:
        json.dump(openai_tools, f, indent=2)

    # ── cursor_mcp_config.json ────────────────────────────────────────────────
    cursor_cfg = _to_cursor_mcp_config(api_url, openai_tools)
    cursor_path = os.path.join(out_dir, "cursor_mcp_config.json")
    with open(cursor_path, "w", encoding="utf-8") as f:
        json.dump(cursor_cfg, f, indent=2)

    print(f"[openai_spec] wrote {tools_path}")
    print(f"[openai_spec] wrote {cursor_path}")
    return {"openai_tools": tools_path, "cursor_mcp_config": cursor_path}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export CogniRepo tool specs")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    paths = export(out_dir=args.out_dir)
    if paths:
        print("\nSetup steps:")
        print("  Cursor/Copilot: copy adapters/cursor_mcp_config.json → .cursor/mcp.json")
        print("  OpenAI/GPT:     reference adapters/openai_tools.json in your tools array")
        print("  Codex/Copilot:  set OPENAI_BASE_URL=http://localhost:8080/v1")
