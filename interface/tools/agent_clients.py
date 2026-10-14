# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Which agent clients have the CogniRepo MCP server configured (read-only; ``GET /api/v1/harness``).

Reads a fixed list of known MCP config files and reports only: client name, config label, the
registered server *names*, the command's basename and whether it looks like CogniRepo. Never
returns args/env (they can hold API keys) and never returns arbitrary file contents.
"""
from __future__ import annotations

import json
import os
from typing import Any

# (label, path ("~" and relative paths allowed), top-level key, client)
MCP_SOURCES: tuple[tuple[str, str, str, str], ...] = (
    ("Project .mcp.json",                   ".mcp.json",                 "mcpServers", "claude-code"),
    ("Project .claude/settings.json",       ".claude/settings.json",     "mcpServers", "claude-code"),
    ("Global ~/.claude.json",               "~/.claude.json",            "mcpServers", "claude-code"),
    ("Cursor .cursor/mcp.json",             ".cursor/mcp.json",          "mcpServers", "cursor"),
    ("VS Code .vscode/mcp.json",            ".vscode/mcp.json",          "servers",    "vscode"),
    ("Gemini CLI ~/.gemini/settings.json",  "~/.gemini/settings.json",   "mcpServers", "gemini-cli"),
)


def _resolve(path: str, repo_root: str) -> str:
    path = os.path.expanduser(path)
    return path if os.path.isabs(path) else os.path.join(repo_root, path)


def _is_cognirepo(name: str, entry: dict) -> bool:
    return "cognirepo" in name.lower() or "cognirepo" in str(entry.get("command", "")).lower()


def last_context_summary(repo_name: str) -> dict[str, Any] | None:
    """Fixed, non-sensitive fields of the shared handoff snapshot (no query text, no sections)."""
    path = os.path.join(os.path.expanduser("~"), ".cognirepo", repo_name, "last_context.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return {
        "generated_at": data.get("generated_at"),
        "tool": data.get("tool"),
        "repo": data.get("repo"),
        "section_count": len(data.get("sections", []) or []),
    }


def agent_clients(repo_root: str) -> dict[str, Any]:
    """Per-client CogniRepo registration state plus the shared last-context summary."""
    clients: dict[str, dict[str, Any]] = {}
    for label, path, key, client in MCP_SOURCES:
        entry = clients.setdefault(client, {"client": client, "registered": False, "configs": []})
        full = _resolve(path, repo_root)
        if not os.path.exists(full):
            continue
        try:
            with open(full, encoding="utf-8") as f:
                servers = json.load(f).get(key, {})
        except (OSError, json.JSONDecodeError, AttributeError):
            entry["configs"].append({"label": label, "readable": False, "servers": []})
            continue
        found = []
        for name, spec in (servers.items() if isinstance(servers, dict) else []):
            spec = spec if isinstance(spec, dict) else {}
            if _is_cognirepo(name, spec):
                found.append({"name": name, "command": os.path.basename(str(spec.get("command", "")))})
        if found:
            entry["registered"] = True
        entry["configs"].append({"label": label, "readable": True, "servers": found})
    repo_name = os.path.basename(repo_root.rstrip(os.sep))
    return {"clients": list(clients.values()), "last_context": last_context_summary(repo_name)}
