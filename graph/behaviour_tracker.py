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

BEHAVIOUR_FILE = ".cognirepo/graph/behaviour.json"
_USEFUL_WINDOW = timedelta(minutes=5)


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class BehaviourTracker:
    """
    Tracks developer and query behaviour to produce per-symbol hit counts
    used by HybridRetriever._behaviour_score_normalized().
    """

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
        }
        self._observer = None
        self._load()

    # ── persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if os.path.exists(BEHAVIOUR_FILE):
            try:
                with open(BEHAVIOUR_FILE, encoding="utf-8") as f:
                    self.data = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass  # start fresh

    def save(self) -> None:
        os.makedirs(os.path.dirname(BEHAVIOUR_FILE), exist_ok=True)
        self.data["updated_at"] = _now()
        with open(BEHAVIOUR_FILE, "w", encoding="utf-8") as f:
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
                self.record_feedback(qid, useful=True, user_action="FILE_EDIT", file_edited=file_path)

    def record_error(self, error_type: str, file_path: str) -> None:
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
        from indexer.file_watcher import create_watcher  # local import avoids circular

        self._observer = create_watcher(path, indexer, self.graph, self, session_id)

    def stop_watching(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None
