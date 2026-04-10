# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Main REPL event loop for CogniRepo.

Chooses RichUI or StdlibUI automatically and dispatches:
  - /command syntax → commands.dispatch()
  - bare text       → classify → local resolver → model stream
"""
from __future__ import annotations

import json
import os
import sys

from cli.repl.ui import make_ui
from cli.repl.commands import dispatch as slash_dispatch
from cli.cli_config import load_cli_config

VERSION = "0.2.0"


def _get_project_stats() -> tuple[str, int, int]:
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
        memory_count = LocalVectorDB().index.ntotal
    except Exception:  # pylint: disable=broad-except
        pass
    try:
        from graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        graph_nodes = KnowledgeGraph().G.number_of_nodes()
    except Exception:  # pylint: disable=broad-except
        pass
    return project_name, memory_count, graph_nodes


def _ctrl_c_count_inc(state: dict) -> int:
    state["ctrl_c_count"] = state.get("ctrl_c_count", 0) + 1
    return state["ctrl_c_count"]


def _auto_save_exchange(state: dict, user_msg: str, assistant_msg: str) -> None:
    """Persist this exchange to the session store (if persist=true in config)."""
    cfg = state.get("cli_cfg")
    if cfg is None or not cfg.session.persist:
        return
    try:
        from orchestrator.session import (  # pylint: disable=import-outside-toplevel
            create_session, append_exchange, load_session,
        )
        sid = state.get("session_id")
        session = load_session(sid) if sid else None
        if session is None:
            session = create_session(model=state.get("force_model") or "")
            state["session_id"] = session["session_id"]
        append_exchange(session, user_msg, assistant_msg,
                        max_exchanges=cfg.session.max_exchanges)
    except Exception:  # pylint: disable=broad-except
        pass  # never break the REPL over persistence errors


def run_repl() -> None:
    """
    Start the interactive REPL.
    Falls back to StdlibUI if rich/prompt_toolkit are not installed.
    """
    if not sys.stdin.isatty():
        return

    ui = make_ui()

    # ── imports deferred to avoid startup cost ────────────────────────────────
    from orchestrator.classifier import classify  # pylint: disable=import-outside-toplevel
    from orchestrator.context_builder import build as build_context  # pylint: disable=import-outside-toplevel
    from orchestrator.router import try_local_resolve, stream_route  # pylint: disable=import-outside-toplevel

    project_name, memory_count, graph_nodes = _get_project_stats()
    ui.print(
        f"CogniRepo v{VERSION} — {project_name} "
        f"({memory_count} memories, {graph_nodes} graph nodes)"
    )
    ui.print("Type /help for commands, /exit or Ctrl+D to quit.\n")

    # ── warm up the embedded docs index (background, never blocks startup) ────
    try:
        import threading  # pylint: disable=import-outside-toplevel
        from cli.docs_index import ensure_docs_index  # pylint: disable=import-outside-toplevel
        threading.Thread(target=ensure_docs_index, daemon=True, name="docs-index-warmup").start()
    except Exception:  # pylint: disable=broad-except
        pass

    # ── load CLI config ───────────────────────────────────────────────────────
    cli_cfg = load_cli_config()

    # ── session persistence: restore last session if persist=true ─────────────
    restored_session: dict | None = None
    if cli_cfg.session.persist:
        try:
            from orchestrator.session import load_current_session  # pylint: disable=import-outside-toplevel
            restored_session = load_current_session()
        except Exception:  # pylint: disable=broad-except
            pass

    # Session state shared between commands and the main loop
    state: dict = {
        "messages_history": list(restored_session["messages"]) if restored_session else [],
        "force_model": cli_cfg.model.prefer or None,
        "ctrl_c_count": 0,
        "session_id": restored_session["session_id"] if restored_session else None,
        "cli_cfg": cli_cfg,
    }

    while True:
        # ── input ─────────────────────────────────────────────────────────────
        try:
            query = ui.prompt(">>> ").strip()
            state["ctrl_c_count"] = 0
        except EOFError:
            ui.print("\nGoodbye.")
            break
        except KeyboardInterrupt:
            count = _ctrl_c_count_inc(state)
            if count >= 2:
                ui.print("\nGoodbye.")
                break
            ui.print("\n  (use /exit or Ctrl+D to leave; press Ctrl+C again to force quit)")
            continue

        if not query:
            continue

        # ── slash commands ─────────────────────────────────────────────────────
        if query.startswith("/"):
            parts = query[1:].split(None, 1)
            cmd = parts[0].lower() if parts else ""
            args = parts[1] if len(parts) > 1 else ""
            # Legacy bare commands (no slash) kept for backwards compat
            if cmd in ("exit", "quit"):
                ui.print("Goodbye.")
                break
            keep_going = slash_dispatch(cmd, args, ui, state)
            if not keep_going:
                break
            continue

        # Legacy bare commands (no slash) — backwards compat
        lower = query.lower()
        if lower in ("exit", "quit"):
            ui.print("Goodbye.")
            break
        if lower == "help":
            slash_dispatch("help", "", ui, state)
            continue
        if lower in ("memories", "graph", "clear", "status", "history"):
            slash_dispatch(lower, "", ui, state)
            continue

        # ── classify ───────────────────────────────────────────────────────────
        clf = classify(query, force_model=state.get("force_model"))

        # ── QUICK/FAST: try local resolver ────────────────────────────────────
        if clf.tier in ("QUICK", "FAST") and not state.get("force_model"):
            bundle = build_context(query, tier="FAST", episode_limit=0)
            local_answer = try_local_resolve(query, bundle)
            if local_answer is not None:
                ui.tier_label("QUICK", "local")
                ui.print(local_answer)
                state["messages_history"].extend([
                    {"role": "user", "content": query},
                    {"role": "assistant", "content": local_answer},
                ])
                _auto_save_exchange(state, query, local_answer)
                continue

        # ── stream from model ──────────────────────────────────────────────────
        ui.tier_label(clf.tier, clf.model)
        try:
            response_text = ui.stream_chunks(
                stream_route(
                    query,
                    messages_history=state["messages_history"] or None,
                    force_model=state.get("force_model"),
                )
            )
        except KeyboardInterrupt:
            ui.print("")
            continue

        if response_text:
            state["messages_history"].extend([
                {"role": "user", "content": query},
                {"role": "assistant", "content": response_text},
            ])
            # ── auto-save to session store ─────────────────────────────────────
            _auto_save_exchange(state, query, response_text)
