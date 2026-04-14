# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Behaviour tracker — records query-retrieval-edit chains and file co-occurrence
to build per-symbol usefulness weights for the hybrid retrieval scorer.

Persists to .cognirepo/graph/behaviour.json
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

from graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType
from graph.graph_utils import make_node_id

if TYPE_CHECKING:
    from indexer.ast_indexer import ASTIndexer

from config.paths import get_path

def _behaviour_file() -> str:
    return get_path("graph/behaviour.json")
_USEFUL_WINDOW = timedelta(minutes=5)


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class BehaviourTracker:
    """
    Tracks developer and query behaviour to produce per-symbol hit counts
    used by HybridRetriever._behaviour_score_normalized().
    """

    # Number of queries to buffer before auto-summarising interaction style
    _STYLE_SUMMARIZE_EVERY = 10

    def __init__(self, graph: KnowledgeGraph) -> None:
        self.graph = graph
        self.data: dict = {
            "version": 1,
            "updated_at": _now(),
            "symbol_weights": {},
            "query_history": {},
            "file_edit_cooccurrence": {},
            "error_patterns": {},
            "session_registry": {},
            "interaction_style": {
                # Ring buffer of recent query texts (capped at 50)
                "query_patterns": [],
                # Term frequency: {term: count} extracted from queries
                "terminology": {},
                # "detailed" | "concise" | "unknown" — inferred from query length
                "preferred_depth": "unknown",
                # ISO timestamp of last summarisation into semantic memory
                "last_summarized": None,
            },
        }
        self._observer = None
        self._load()

    # ── persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if os.path.exists(_behaviour_file()):
            try:
                with open(_behaviour_file(), encoding="utf-8") as f:
                    self.data = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass  # start fresh

    def save(self) -> None:
        """Persist the behaviour data to behaviour.json."""
        os.makedirs(os.path.dirname(_behaviour_file()), exist_ok=True)
        self.data["updated_at"] = _now()
        with open(_behaviour_file(), "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    # ── query tracking ────────────────────────────────────────────────────────

    def record_query(
        self,
        query_id: str,
        query_text: str,
        retrieved_symbols: list[str],
    ) -> None:
        """
        Log a retrieval event. Adds QUERY node + QUERIED_WITH edges to graph.
        """
        self.data["query_history"][query_id] = {
            "query_text": query_text,
            "timestamp": _now(),
            "retrieved_symbols": retrieved_symbols,
            "useful": None,
        }

        # ── interaction style: buffer query text ─────────────────────────────
        style = self.data.setdefault("interaction_style", {
            "query_patterns": [], "terminology": {},
            "preferred_depth": "unknown", "last_summarized": None,
        })
        patterns: list = style.setdefault("query_patterns", [])
        patterns.append(query_text)
        if len(patterns) > 50:
            patterns.pop(0)  # keep last 50
        # crude term frequency (split on non-alpha, skip short words)
        terms: dict = style.setdefault("terminology", {})
        for word in query_text.lower().split():
            word = word.strip(".,!?;:()'\"")
            if len(word) > 3:
                terms[word] = terms.get(word, 0) + 1
        # infer preferred depth from median query length
        avg_len = sum(len(q) for q in patterns) / max(len(patterns), 1)
        style["preferred_depth"] = (
            "detailed" if avg_len > 120
            else "concise" if avg_len < 40
            else "medium"
        )

        # graph: add QUERY node and edges to each retrieved symbol
        q_node = make_node_id("QUERY", query_id)
        self.graph.add_node(q_node, NodeType.QUERY, text=query_text)
        for sym in retrieved_symbols:
            if self.graph.node_exists(sym):
                self.graph.add_edge(q_node, sym, EdgeType.QUERIED_WITH)

    def record_feedback(
        self,
        query_id: str,
        useful: bool,
        user_action: str | None = None,
        file_edited: str | None = None,
    ) -> None:
        """
        Mark a query as useful/not-useful and increment hit_count for its symbols.
        """
        qh = self.data["query_history"].get(query_id)
        if not qh:
            return

        qh["useful"] = useful
        if user_action:
            qh["user_action_within_5min"] = user_action
        if file_edited:
            qh["file_edited"] = file_edited

        if useful:
            sw = self.data["symbol_weights"]
            for sym in qh.get("retrieved_symbols", []):
                if sym not in sw:
                    sw[sym] = {"hit_count": 0, "last_hit": None, "relevance_feedback": 0.0}
                sw[sym]["hit_count"] += 1
                sw[sym]["last_hit"] = _now()
                sw[sym]["relevance_feedback"] = min(
                    1.0, sw[sym]["relevance_feedback"] + 0.1
                )

    def record_file_edit(self, file_path: str, session_id: str) -> None:
        """
        Called by FileWatcher on .py file change.
        1. Updates file_edit_cooccurrence with other files touched this session.
        2. Auto-marks recent queries useful if edit happened within 5-min window.
        3. Adds CO_OCCURS edges to graph.
        """
        sr = self.data["session_registry"]
        if session_id not in sr:
            sr[session_id] = {"start": _now(), "queries": [], "files_touched": []}
        session = sr[session_id]

        co = self.data["file_edit_cooccurrence"]
        for other_file in session["files_touched"]:
            if other_file == file_path:
                continue
            co.setdefault(file_path, {})
            co[file_path][other_file] = co[file_path].get(other_file, 0) + 1
            co.setdefault(other_file, {})
            co[other_file][file_path] = co[other_file].get(file_path, 0) + 1
            # graph edge
            self.graph.add_node(file_path, NodeType.FILE)
            self.graph.add_node(other_file, NodeType.FILE)
            w = co[file_path][other_file]
            self.graph.add_edge(file_path, other_file, EdgeType.CO_OCCURS, weight=float(w))

        if file_path not in session["files_touched"]:
            session["files_touched"].append(file_path)

        # auto-mark recent queries as useful
        cutoff = datetime.now(tz=timezone.utc) - _USEFUL_WINDOW
        for qid, qh in self.data["query_history"].items():
            if qh.get("useful") is not None:
                continue
            try:
                qts = datetime.fromisoformat(qh["timestamp"])
            except (KeyError, ValueError):
                continue
            if qts >= cutoff:
                self.record_feedback(
                    qid, useful=True, user_action="FILE_EDIT",
                    file_edited=file_path,
                )

    def record_error(self, error_type: str, file_path: str) -> None:
        """Log a syntax or runtime error associated with a file."""
        ep = self.data["error_patterns"]
        if error_type not in ep:
            ep[error_type] = {"count": 0, "files": [], "last_seen": None}
        ep[error_type]["count"] += 1
        ep[error_type]["last_seen"] = _now()
        if file_path not in ep[error_type]["files"]:
            ep[error_type]["files"].append(file_path)

    # ── score access ──────────────────────────────────────────────────────────

    def get_behaviour_score(self, symbol_id: str) -> float:
        """Raw hit_count for symbol_id; 0.0 if unseen."""
        return float(self.data["symbol_weights"].get(symbol_id, {}).get("hit_count", 0))

    def get_all_scores(self) -> dict[str, float]:
        """Returns {symbol_id: hit_count} for all tracked symbols."""
        return {k: float(v["hit_count"]) for k, v in self.data["symbol_weights"].items()}

    # ── file watcher lifecycle ────────────────────────────────────────────────

    def start_watching(
        self,
        path: str,
        session_id: str,
        indexer: "ASTIndexer",
    ) -> None:
        """Start a watchdog Observer for the given repo path."""
        from indexer.file_watcher import create_watcher  # pylint: disable=import-outside-toplevel

        self._observer = create_watcher(path, indexer, self.graph, self, session_id)

    def stop_watching(self) -> None:
        """Stop and join the file watcher thread."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None

    # ── interaction style summariser ──────────────────────────────────────────

    def summarize_interaction_style(self) -> bool:
        """
        When query_patterns buffer reaches _STYLE_SUMMARIZE_EVERY entries,
        build a natural-language summary and store it as a semantic memory
        with importance=0.8 and source="interaction_style".

        Returns True if a memory was stored, False otherwise.
        """
        style = self.data.get("interaction_style", {})
        patterns: list = style.get("query_patterns", [])
        if len(patterns) < self._STYLE_SUMMARIZE_EVERY:
            return False

        try:
            from tools.store_memory import store_memory  # pylint: disable=import-outside-toplevel
            # top 5 terms by frequency
            terms: dict = style.get("terminology", {})
            top_terms = sorted(terms, key=lambda k: terms[k], reverse=True)[:5]
            depth = style.get("preferred_depth", "unknown")
            sample_queries = patterns[-3:]  # last 3 for illustration

            summary = (
                f"User interaction style: prefers {depth} answers. "
                f"Common terminology: {', '.join(top_terms) if top_terms else 'N/A'}. "
                f"Recent query examples: {' | '.join(q[:80] for q in sample_queries)}."
            )
            store_memory(summary, source="interaction_style", importance=0.8)
            style["last_summarized"] = _now()
            # Clear buffer after summarising so next batch is fresh
            style["query_patterns"] = []
            style["terminology"] = {}
            return True
        except Exception:  # pylint: disable=broad-except
            return False  # always best-effort
