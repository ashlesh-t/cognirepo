#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Single-source-of-truth generator for CogniRepo's MCP tool-schema artifacts.

The only place a tool's schema is hand-written is its @mcp.tool() decorated
function (signature + docstring) in interface/server/mcp_server.py. This
script introspects the live FastMCP registry and regenerates every derived
artifact from it:

    interface/server/manifest.json   — via interface.server.mcp_server._write_manifest()
    glama.json                       — "tools" array only; other top-level keys preserved
    interface/adapters/openai_tools.json
    interface/adapters/cursor_mcp_config.json  — via interface.adapters.openai_spec.export()

Usage:
    python scripts/gen_tool_specs.py           # regenerate all four files
    python scripts/gen_tool_specs.py --check   # exit 1 if any artifact would change (CI drift gate)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
GLAMA_PATH = REPO_ROOT / "glama.json"


def _tool_to_glama_entry(tool: dict) -> dict:
    """manifest.json uses 'parameters'; glama.json's schema uses 'inputSchema' — same content."""
    return {
        "name": tool["name"],
        "description": tool["description"],
        "inputSchema": tool["parameters"],
    }


def regenerate(check: bool = False) -> bool:
    """
    Regenerate manifest.json, glama.json's tools array, and the openai/cursor
    adapter files. Returns True if the working tree changed (or, in --check
    mode, would have changed).
    """
    sys.path.insert(0, str(REPO_ROOT))
    from interface.server.mcp_server import _build_manifest  # pylint: disable=import-outside-toplevel

    manifest = _build_manifest()
    manifest_path = REPO_ROOT / "interface" / "server" / "manifest.json"
    before_manifest = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else None
    after_manifest = json.dumps(manifest, indent=2)

    glama = json.loads(GLAMA_PATH.read_text(encoding="utf-8")) if GLAMA_PATH.exists() else {}
    before_glama = json.dumps(glama, indent=2) if glama else None
    glama["tools"] = [_tool_to_glama_entry(t) for t in manifest["tools"]]
    after_glama = json.dumps(glama, indent=2)

    changed = before_manifest != after_manifest or before_glama != after_glama

    if check:
        return changed

    # openai_spec.export() calls _write_manifest() internally (same _build_manifest()
    # output) and also regenerates openai_tools.json + cursor_mcp_config.json — one
    # call keeps manifest.json in sync with those two derived files.
    from interface.adapters.openai_spec import export  # pylint: disable=import-outside-toplevel
    export()
    GLAMA_PATH.write_text(after_glama, encoding="utf-8")

    print(f"[gen_tool_specs] wrote {manifest_path} ({len(manifest['tools'])} tools)", file=sys.stderr)
    print(f"[gen_tool_specs] wrote {GLAMA_PATH} ({len(glama['tools'])} tools)", file=sys.stderr)
    return changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="Exit 1 if any artifact is out of sync with the decorated tools, without writing.",
    )
    args = parser.parse_args()
    drifted = regenerate(check=args.check)
    if args.check and drifted:
        print(
            "[gen_tool_specs] DRIFT: manifest.json/glama.json are out of sync with the "
            "@mcp.tool() registry. Run: python scripts/gen_tool_specs.py",
            file=sys.stderr,
        )
        sys.exit(1)
