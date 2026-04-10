# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Interactive REPL for CogniRepo.

Usage
-----
    cognirepo          (no arguments, stdin is a tty)
    cognirepo chat

Features
--------
- readline history / arrow-key navigation (no extra deps)
- Special commands: help, memories, graph, clear, exit, quit
- Streams model responses with [TIER → model] prefix
- Skipped automatically when stdin is not a tty
"""
from __future__ import annotations

import json
import os
import sys

VERSION = "0.1.0"

_HELP_TEXT = """\
CogniRepo REPL commands:
  help       — show this help
  memories   — show top 5 stored memories
  graph      — show knowledge graph stats
  clear      — reset conversation history
  exit/quit  — exit (also Ctrl+D)

Any other input is sent to the model router."""


# ── project stats ─────────────────────────────────────────────────────────────

def _get_project_stats() -> tuple[str, int, int]:
    """Return (project_name, memory_count, graph_node_count)."""
    project_name = os.path.basename(os.getcwd()) or "."
    memory_count = 0
    graph_nodes = 0

    try:
        cfg_path = ".cognirepo/config.json"
        if os.path.exists(cfg_path):
            with open(cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
            project_name = cfg.get("project_name", project_name)
    except Exception:  # pylint: disable=broad-except
        pass

    try:
        from vector_db.local_vector_db import LocalVectorDB  # pylint: disable=import-outside-toplevel
        db = LocalVectorDB()
        memory_count = db.index.ntotal
    except Exception:  # pylint: disable=broad-except
        pass

    try:
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        kg = KnowledgeGraph()
        graph_nodes = kg.G.number_of_nodes()
    except Exception:  # pylint: disable=broad-except
        pass

    return project_name, memory_count, graph_nodes


# ── REPL special commands ─────────────────────────────────────────────────────

def _cmd_memories() -> None:
    try:
        from vector_db.local_vector_db import LocalVectorDB  # pylint: disable=import-outside-toplevel
        db = LocalVectorDB()
        items = db.metadata[-5:] if db.metadata else []
        if not items:
            print("  (no memories stored)")
            return
        for i, item in enumerate(reversed(items), 1):
            importance = item.get("importance", "?")
            text = item.get("text", "")[:80]
            print(f"  {i}. [{importance}] {text}")
    except Exception as exc:  # pylint: disable=broad-except
        print(f"  (error: {exc})")


def _cmd_graph() -> None:
    try:
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        kg = KnowledgeGraph()
        nodes = kg.G.number_of_nodes()
        edges = kg.G.number_of_edges()
        print(f"  nodes={nodes}  edges={edges}")
    except Exception as exc:  # pylint: disable=broad-except
        print(f"  (error: {exc})")


# ── main entry point ──────────────────────────────────────────────────────────

def run_repl() -> None:
    """
    Start the interactive REPL.  Returns immediately if stdin is not a tty.
    Blocks until the user exits.
    """
    if not sys.stdin.isatty():
        return

    # Enable readline history + arrow-key navigation (no extra deps)
    try:
        import readline  # pylint: disable=import-outside-toplevel
        readline.parse_and_bind("tab: complete")
    except ImportError:
        pass

    project_name, memory_count, graph_nodes = _get_project_stats()
    print(
        f"CogniRepo v{VERSION} — project: {project_name} "
        f"({memory_count} memories, {graph_nodes} graph nodes)"
    )
    print("Type 'exit' or Ctrl+D to quit. 'help' for commands.\n")

    from orchestrator.classifier import classify          # pylint: disable=import-outside-toplevel
    from orchestrator.context_builder import build as build_context  # pylint: disable=import-outside-toplevel
    from orchestrator.router import try_local_resolve, stream_route  # pylint: disable=import-outside-toplevel

    messages_history: list[dict] = []

    while True:
        try:
            query = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not query:
            continue

        lower = query.lower()

        # ── special commands ──────────────────────────────────────────────────
        if lower in ("exit", "quit"):
            print("Goodbye.")
            break
        if lower == "help":
            print(_HELP_TEXT)
            continue
        if lower == "memories":
            _cmd_memories()
            continue
        if lower == "graph":
            _cmd_graph()
            continue
        if lower == "clear":
            messages_history = []
            print("  (conversation history cleared)")
            continue

        # ── classify to get tier/model for the label ──────────────────────────
        clf = classify(query)

        # ── STANDARD: try local resolver first ───────────────────────────────
        if clf.tier == "STANDARD":
            bundle = build_context(query, tier="STANDARD", episode_limit=0)
            local_answer = try_local_resolve(query, bundle)
            if local_answer is not None:
                print("[STANDARD → local] ", end="", flush=True)
                print(local_answer)
                messages_history.append({"role": "user", "content": query})
                messages_history.append({"role": "assistant", "content": local_answer})
                continue

        # ── stream from model ─────────────────────────────────────────────────
        print(f"[{clf.tier} → {clf.model}] ", end="", flush=True)
        full_text: list[str] = []
        try:
            for chunk in stream_route(
                query,
                messages_history=messages_history if messages_history else None,
            ):
                print(chunk, end="", flush=True)
                full_text.append(chunk)
        except KeyboardInterrupt:
            print()
            continue
        print()
        response_text = "".join(full_text)
        if response_text:
            messages_history.append({"role": "user", "content": query})
            messages_history.append({"role": "assistant", "content": response_text})
