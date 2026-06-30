# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tools/prime_session.py — Session bootstrap brief for agent orientation.

Extracted from cli/main.py::_cmd_prime() so MCP tools and the CLI can share
the same implementation without circular imports.
"""
from __future__ import annotations

import datetime
import json
import os

from core.config.paths import get_path


def _detect_blind_spots(index_health: dict) -> list[str]:
    """
    Derive known blind spots from the current index state.

    Each entry is a concise warning string that agents should surface to the
    user so they know what context_pack / retrieve_memory cannot answer.
    """
    spots: list[str] = []

    # ── 1. Stale index ────────────────────────────────────────────────────────
    try:
        last_indexed = index_health.get("last_indexed", "")
        if last_indexed and last_indexed != "not indexed":
            age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(last_indexed)
            hours = age.total_seconds() / 3600
            if hours > 48:
                spots.append(
                    f"Index is {int(hours)}h old — recent file changes not reflected. "
                    "Run: cognirepo index-repo ."
                )
            elif hours > 24:
                spots.append(
                    f"Index is {int(hours)}h old — may miss recent changes. "
                    "Run: cognirepo index-repo . to refresh."
                )
    except Exception:  # pylint: disable=broad-except
        pass

    # ── 2. Not indexed at all ─────────────────────────────────────────────────
    if index_health.get("symbols", 0) == 0:
        spots.append(
            "No symbols indexed — symbol lookup and context_pack will fail. "
            "Run: cognirepo index-repo ."
        )

    # ── 3. Knowledge graph empty or corrupted ────────────────────────────────
    try:
        from data.graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        import os as _os  # pylint: disable=import-outside-toplevel
        kg = KnowledgeGraph()
        pkl_path = get_path("graph/graph.pkl")
        pkl_exists = _os.path.exists(pkl_path)
        if kg.G.number_of_nodes() == 0:
            if pkl_exists:
                spots.append(
                    "Knowledge graph file exists but loaded empty (likely corrupted). "
                    "Cross-file call relationships unavailable. "
                    "Run: cognirepo index-repo . to rebuild."
                )
            elif index_health.get("symbols", 0) > 0:
                spots.append(
                    "Knowledge graph not built — who_calls() and subgraph() unavailable. "
                    "Run: cognirepo index-repo ."
                )
    except Exception:  # pylint: disable=broad-except
        pass

    # ── 4. Semantic store empty ───────────────────────────────────────────────
    try:
        from core.vector_db.factory import get_vector_adapter  # pylint: disable=import-outside-toplevel
        if get_vector_adapter().count() == 0:
            spots.append(
                "Semantic memory empty — retrieve_memory() and context_pack() will "
                "return no vector matches. Run: cognirepo index-repo . (re-seeds docs)."
            )
    except Exception:  # pylint: disable=broad-except
        pass

    # ── 5. Tier 2 indexing still pending ─────────────────────────────────────
    try:
        from core.config.paths import pending_tier2_path  # pylint: disable=import-outside-toplevel
        t2_path = pending_tier2_path()
        if _os.path.exists(t2_path):
            with open(t2_path, encoding="utf-8") as _f:
                t2 = json.load(_f)
            n_files = len(t2.get("files", []))
            embed_pending = t2.get("embed_pending", False)
            parts = []
            if n_files:
                parts.append(f"{n_files:,} files")
            if embed_pending:
                parts.append("FAISS embeddings")
            if parts:
                spots.append(
                    f"Background indexing incomplete ({', '.join(parts)} pending) — "
                    "symbol lookup may be partial. Run: cognirepo index-repo . --tier 2"
                )
    except Exception:  # pylint: disable=broad-except
        pass

    # ── 6. Architecture summaries missing ────────────────────────────────────
    try:
        sm_path = get_path("index/summaries.json")
        if not _os.path.exists(sm_path):
            if index_health.get("symbols", 0) > 0:
                spots.append(
                    "Architecture summaries not generated — architecture_overview() "
                    "will return no results. Run: cognirepo summarize"
                )
    except Exception:  # pylint: disable=broad-except
        pass

    # ── 7. Microservice children with no API edges ───────────────────────────
    try:
        from data.graph.org_graph import get_org_graph  # pylint: disable=import-outside-toplevel
        import os as _os2  # pylint: disable=import-outside-toplevel
        _og = get_org_graph()
        _children = _og.get_children(_os2.getcwd())
        if _children:
            _api_edges = [
                (u, v) for u, v, d in _og.G.edges(data=True)
                if d.get("kind") == "CALLS_API" and d.get("direction") == "forward"
            ]
            if not _api_edges:
                spots.append(
                    f"{len(_children)} child service(s) registered but no CALLS_API edges "
                    "detected yet — service-to-service call chains are invisible. "
                    "Run cognirepo index-repo . inside each child to auto-detect HTTP calls, "
                    "or call link_repos() to wire them manually."
                )
            _unindexed = []
            for _cp in _children:
                try:
                    from core.config.paths import _CTX_DIR, get_cognirepo_dir_for_repo as _gcdr2  # pylint: disable=import-outside-toplevel
                    _ctok2 = _CTX_DIR.set(_gcdr2(_cp))
                    try:
                        if not _os2.path.exists(get_path("index/ast_index.json")):
                            _unindexed.append(_os2.path.basename(_cp))
                    finally:
                        _CTX_DIR.reset(_ctok2)
                except Exception:  # pylint: disable=broad-except
                    pass
            if _unindexed:
                spots.append(
                    f"Child service(s) not yet indexed: {', '.join(_unindexed)}. "
                    "Run: cognirepo index-repo . inside each to enable cross-repo search."
                )
    except Exception:  # pylint: disable=broad-except
        pass

    # ── 8. Large repo — context_pack accuracy note ───────────────────────────
    try:
        n_files = index_health.get("files", 0)
        if n_files > 10_000:
            spots.append(
                f"Large repo ({n_files:,} files) — only Tier-1 (direct + hop-2) "
                "files are fully indexed. Low-weight indirect files use lightweight index."
            )
    except Exception:  # pylint: disable=broad-except
        pass

    return spots


def prime_session() -> dict:
    """
    Generate a session bootstrap brief.

    Returns architecture summary, entry points (most-called symbols),
    recent decisions from the learning store, hot symbols from the behaviour
    tracker, and index health (symbol count, file count, last_indexed).

    Used by both `cognirepo prime` (CLI) and `get_session_brief` (MCP tool).
    """
    brief: dict = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "repo": os.path.basename(os.getcwd()),
        "architecture": [],
        "entry_points": [],
        "recent_decisions": [],
        "hot_symbols": [],
        "index_health": {},
        "known_blind_spots" : []
    }

    # ── architecture + recent decisions from learning store ───────────────────
    try:
        from data.memory.learning_store import get_learning_store  # pylint: disable=import-outside-toplevel
        store = get_learning_store()
        arch_learnings = store.retrieve_learnings("architecture overview design", top_k=3)
        brief["architecture"] = [
            {"text": lr.get("text", "")[:600], "type": lr.get("type", "")}
            for lr in arch_learnings
        ]
        recent = store.retrieve_learnings("decision bug fix", top_k=3)
        brief["recent_decisions"] = [
            {"text": lr.get("text", "")[:600], "type": lr.get("type", "")}
            for lr in recent
        ]
    except Exception:  # pylint: disable=broad-except
        pass

    # ── entry points from knowledge graph (top symbols by in-degree) ─────────
    try:
        from data.graph.knowledge_graph import KnowledgeGraph  # pylint: disable=import-outside-toplevel
        kg = KnowledgeGraph()
        if kg.G.number_of_nodes() > 0:
            top = sorted(
                [(n, d) for n, d in kg.G.in_degree() if not n.startswith("concept::")],
                key=lambda x: x[1],
                reverse=True,
            )[:5]
            brief["entry_points"] = [
                {"symbol": n.replace("symbol::", ""), "call_count": deg}
                for n, deg in top
            ]
    except Exception:  # pylint: disable=broad-except
        pass

    # ── queried symbols from behaviour tracker ───────────────────────────────
    # These are the symbols most often surfaced by past QUERIES (retrieval
    # feedback), NOT recently-edited code. The old "hot_symbols" label misled
    # agents into reporting CI/config files as "hottest symbols". Both keys
    # are emitted for one release; hot_symbols is deprecated.
    try:
        from data.graph.knowledge_graph import KnowledgeGraph as _KG  # pylint: disable=import-outside-toplevel
        from data.graph.behaviour_tracker import BehaviourTracker  # pylint: disable=import-outside-toplevel
        bt = BehaviourTracker(_KG())
        weights = bt.data.get("symbol_weights", {})
        hot = sorted(
            [(k, v.get("hit_count", 0)) for k, v in weights.items()],
            key=lambda x: x[1],
            reverse=True,
        )[:5]
        _queried = [
            {"symbol": k.split("::")[-1], "path": k, "score": round(v, 2)}
            for k, v in hot
        ]
        brief["queried_symbols"] = _queried
        brief["hot_symbols"] = _queried  # deprecated alias — remove in 1.2
    except Exception:  # pylint: disable=broad-except
        pass

    # ── recently modified files (git) ────────────────────────────────────────
    try:
        import subprocess as _sp  # pylint: disable=import-outside-toplevel
        _out = _sp.check_output(
            ["git", "log", "--name-only", "--pretty=format:", "-n", "20"],
            text=True, stderr=_sp.DEVNULL,
        )
        _recent = list(dict.fromkeys(l for l in _out.splitlines() if l.strip()))[:8]
        if _recent:
            brief["recently_modified_files"] = _recent
    except Exception:  # pylint: disable=broad-except
        pass

    # ── index health ──────────────────────────────────────────────────────────
    try:
        with open(get_path("index/ast_index.json"), encoding="utf-8") as f:
            idx = json.load(f)
        brief["index_health"] = {
            "symbols": idx.get("total_symbols", 0),
            "files": len(idx.get("files", {})),
            "last_indexed": idx.get("indexed_at", "unknown"),
        }
    except (OSError, json.JSONDecodeError):
        brief["index_health"] = {"symbols": 0, "files": 0, "last_indexed": "not indexed"}

    # ── known blind spots ─────────────────────────────────────────────────────
    try:
        brief["known_blind_spots"] = _detect_blind_spots(brief["index_health"])
    except Exception:  # pylint: disable=broad-except
        pass  # always best-effort — never block the brief

    # Cold-start guidance — tell agents what to run when data is missing
    if not brief["architecture"]:
        if brief["index_health"].get("symbols", 0) == 0:
            brief["setup_required"] = (
                "Index not built. Run: cognirepo index-repo . "
                "(then cognirepo summarize for architecture overview)"
            )
        else:
            brief["setup_required"] = (
                "Architecture summaries missing. Run: cognirepo summarize"
            )

    return brief
