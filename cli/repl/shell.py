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


def _auto_save_exchange(
    state: dict,
    user_msg: str,
    assistant_msg: str,
    sub_queries: list[dict] | None = None,
) -> None:
    """Persist this exchange to the session store (if persist=true in config).

    sub_queries: optional list of sub-agent records to store under
                 exchange["sub_queries"] for multi-agent turns.
    """
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
        append_exchange(
            session, user_msg, assistant_msg,
            max_exchanges=cfg.session.max_exchanges,
            extra={"sub_queries": sub_queries} if sub_queries else None,
        )
    except Exception:  # pylint: disable=broad-except
        pass  # never break the REPL over persistence errors


def _fire_sub_agents(query: str, registry) -> None:
    """
    For EXPERT-tier queries, dispatch a lightweight sub-agent lookup via gRPC
    in a background thread.  The sub-agent result is stored in the registry
    and rendered as a grey panel after the primary response completes.

    Only fires when COGNIREPO_MULTI_AGENT_ENABLED=true (checked by caller).
    Silently drops errors — the primary response must always complete.
    """
    import threading  # pylint: disable=import-outside-toplevel

    # Heuristic: extract the first noun phrase as the sub-query focus
    sub_q = f"quick lookup: {query[:120]}"
    agent_id = registry.start(sub_q)

    def _run():
        try:
            from rpc.client import CogniRepoClient  # pylint: disable=import-outside-toplevel
            import os  # pylint: disable=import-outside-toplevel
            port = int(os.environ.get("COGNIREPO_GRPC_PORT", "50051"))
            with CogniRepoClient(port=port) as client:
                resp = client.sub_query(
                    query=sub_q,
                    target_tier="STANDARD",
                    max_tokens=256,
                    timeout=15.0,
                )
                registry.finish(agent_id, result=resp.result)
        except Exception as exc:  # pylint: disable=broad-except
            registry.fail(agent_id, error=str(exc))

    threading.Thread(target=_run, daemon=True, name=f"sub-agent-{agent_id}").start()


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

    # ── detect API keys ───────────────────────────────────────────────────────
    import os as _os  # pylint: disable=import-outside-toplevel
    _keys_present = [
        k for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "GROK_API_KEY")
        if _os.environ.get(k)
    ]
    _multi_agent = _os.environ.get("COGNIREPO_MULTI_AGENT_ENABLED", "false").lower() == "true"

    # ── detect current tier/model from config ─────────────────────────────────
    _tier_summary = "QUICK→local | STANDARD→Haiku | COMPLEX→Sonnet | EXPERT→Opus"
    try:
        from config.paths import get_path as _get_path  # pylint: disable=import-outside-toplevel
        import json as _json  # pylint: disable=import-outside-toplevel
        with open(_get_path("config.json"), encoding="utf-8") as _f:
            _cfg = _json.load(_f)
        _models = _cfg.get("models", {})
        if _models:
            _tier_summary = " | ".join(
                f"{t}→{_models[t].get('model', '?').split('-')[2] if '-' in _models[t].get('model', '') else _models[t].get('model', '?')}"
                for t in ("QUICK", "STANDARD", "COMPLEX", "EXPERT") if t in _models
            )
    except Exception:  # pylint: disable=broad-except
        pass

    ui.print(f"╔═ CogniRepo v{VERSION} ══════════════════════════════════════╗")
    ui.print(f"  Project : {project_name}")
    ui.print(f"  Index   : {memory_count} memories · {graph_nodes} graph nodes")
    ui.print(f"  Tiers   : {_tier_summary}")
    ui.print(f"  API keys: {', '.join(_keys_present) if _keys_present else '⚠ none set — QUICK tier only'}")
    ui.print(f"  Agents  : {'enabled (gRPC)' if _multi_agent else 'disabled  (set COGNIREPO_MULTI_AGENT_ENABLED=true)'}")
    ui.print(f"  Help    : /help · /status · /model · /exit or Ctrl+D")
    ui.print("")

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

    # ── multi-agent: per-turn registry ────────────────────────────────────────
    import os  # pylint: disable=import-outside-toplevel
    _multi_agent_enabled = os.environ.get("COGNIREPO_MULTI_AGENT_ENABLED", "false").lower() == "true"
    from cli.repl.agents_panel import AgentRegistry  # pylint: disable=import-outside-toplevel
    _agent_registry = AgentRegistry()

    # Session state shared between commands and the main loop
    state: dict = {
        "messages_history": list(restored_session["messages"]) if restored_session else [],
        "force_model": cli_cfg.model.prefer or None,
        "ctrl_c_count": 0,
        "session_id": restored_session["session_id"] if restored_session else None,
        "cli_cfg": cli_cfg,
        "agent_registry": _agent_registry,
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
        if clf.tier in ("QUICK", "STANDARD") and not state.get("force_model"):
            bundle = build_context(query, tier="STANDARD", episode_limit=0)
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

        # ── multi-agent: fire sub-agents for EXPERT queries ──────────────────
        _agent_registry.clear()
        if _multi_agent_enabled and clf.tier == "EXPERT":
            _fire_sub_agents(query, _agent_registry)

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

        # ── render sub-agent panel after primary response ─────────────────────
        if _multi_agent_enabled and _agent_registry.all():
            from cli.repl.agents_panel import render_agents_panel  # pylint: disable=import-outside-toplevel
            render_agents_panel(_agent_registry)

        if response_text:
            state["messages_history"].extend([
                {"role": "user", "content": query},
                {"role": "assistant", "content": response_text},
            ])
            # ── auto-save to session store (include sub_queries) ───────────────
            _auto_save_exchange(state, query, response_text,
                                sub_queries=_agent_registry.to_session_records())
