# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Slash-command registry for the CogniRepo REPL.

Each command is registered with @register(name, description).
The handler receives (ui, args_str, session_state) and returns True to
continue the REPL loop or False to exit.
"""
from __future__ import annotations

from typing import Callable

from cli.repl.ui import UI

_REGISTRY: dict[str, tuple[str, Callable]] = {}


def register(name: str, description: str):
    """Decorator: register a slash command handler."""
    def decorator(fn: Callable) -> Callable:
        _REGISTRY[name] = (description, fn)
        return fn
    return decorator


def dispatch(command: str, args_str: str, ui: UI, state: dict) -> bool:
    """
    Dispatch a slash command.
    Returns True to continue REPL, False to exit.
    Prints an error if command is unknown.
    """
    entry = _REGISTRY.get(command)
    if entry is None:
        ui.print(f"  Unknown command: /{command}. Type /help for available commands.")
        return True
    _, handler = entry
    return handler(ui, args_str, state)


def list_commands() -> list[tuple[str, str]]:
    """Return (name, description) pairs for all registered commands."""
    return [(name, desc) for name, (desc, _) in sorted(_REGISTRY.items())]


# ── built-in commands ──────────────────────────────────────────────────────────

@register("help", "Show all available slash commands")
def _cmd_help(ui: UI, _args: str, _state: dict) -> bool:
    rows = list_commands()
    ui.print("\nAvailable commands:")
    for name, desc in rows:
        ui.print(f"  /{name:15s}  {desc}")
    ui.print("")
    return True


@register("clear", "Clear conversation history for this session")
def _cmd_clear(ui: UI, _args: str, state: dict) -> bool:
    state["messages_history"] = []
    ui.status("Conversation history cleared.")
    return True


@register("exit", "Exit the REPL")
def _cmd_exit(ui: UI, _args: str, _state: dict) -> bool:
    ui.print("Goodbye.")
    return False


@register("status", "Show daemon health, FAISS size, graph stats, circuit breaker")
def _cmd_status(ui: UI, _args: str, _state: dict) -> bool:
    try:
        from vector_db.local_vector_db import LocalVectorDB  # pylint: disable=import-outside-toplevel
        db = LocalVectorDB()
        mem_count = db.index.ntotal
    except Exception:  # pylint: disable=broad-except
        mem_count = "?"

    try:
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        kg = KnowledgeGraph()
        nodes = kg.G.number_of_nodes()
        edges = kg.G.number_of_edges()
        graph_info = f"{nodes} nodes / {edges} edges"
    except Exception:  # pylint: disable=broad-except
        graph_info = "?"

    try:
        from memory.circuit_breaker import get_breaker  # pylint: disable=import-outside-toplevel
        cb_state = get_breaker().state.value
    except Exception:  # pylint: disable=broad-except
        cb_state = "?"

    ui.print(f"  Memories (FAISS): {mem_count}")
    ui.print(f"  Knowledge graph:  {graph_info}")
    ui.print(f"  Circuit breaker:  {cb_state}")
    return True


@register("memories", "Show the 5 most recent stored memories")
def _cmd_memories(ui: UI, _args: str, _state: dict) -> bool:
    try:
        from vector_db.local_vector_db import LocalVectorDB  # pylint: disable=import-outside-toplevel
        db = LocalVectorDB()
        items = db.metadata[-5:] if db.metadata else []
        if not items:
            ui.print("  (no memories stored)")
            return True
        for i, item in enumerate(reversed(items), 1):
            importance = item.get("importance", "?")
            text = item.get("text", "")[:80]
            ui.print(f"  {i}. [{importance}] {text}")
    except Exception as exc:  # pylint: disable=broad-except
        ui.print(f"  (error: {exc})")
    return True


@register("graph", "Show knowledge graph statistics")
def _cmd_graph(ui: UI, _args: str, _state: dict) -> bool:
    try:
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        kg = KnowledgeGraph()
        ui.print(f"  nodes={kg.G.number_of_nodes()}  edges={kg.G.number_of_edges()}")
    except Exception as exc:  # pylint: disable=broad-except
        ui.print(f"  (error: {exc})")
    return True


@register("history", "Show conversation history for this session")
def _cmd_history(ui: UI, _args: str, state: dict) -> bool:
    msgs = state.get("messages_history", [])
    if not msgs:
        ui.print("  (no history yet)")
        return True
    for i, msg in enumerate(msgs, 1):
        role = msg.get("role", "?").upper()
        content = msg.get("content", "")[:120]
        ui.print(f"  [{i}] {role}: {content}")
    return True


@register("model", "Show current tier/model or set override: /model set <id>")
def _cmd_model(ui: UI, args: str, state: dict) -> bool:
    parts = args.strip().split()
    if parts and parts[0] == "set" and len(parts) >= 2:
        state["force_model"] = parts[1]
        ui.status(f"Model override set to: {parts[1]}")
    else:
        override = state.get("force_model")
        if override:
            ui.print(f"  Force model: {override}")
        else:
            ui.print("  No model override — using classifier-based routing.")
    return True


@register("search", "Force a Tier-1 docs search: /search <query>")
def _cmd_search(ui: UI, args: str, _state: dict) -> bool:
    from retrieval.docs_search import search_docs  # pylint: disable=import-outside-toplevel
    query = args.strip()
    if not query:
        ui.print("  Usage: /search <query>")
        return True
    try:
        results = search_docs(query)
        if not results:
            ui.print("  No results.")
            return True
        for r in results[:3]:
            path = r.get("path", "?")
            line = r.get("line", "?")
            ctx = (r.get("context") or "")[:100]
            ui.print(f"  {path}:{line}  {ctx}")
    except Exception as exc:  # pylint: disable=broad-except
        ui.print(f"  (error: {exc})")
    return True
