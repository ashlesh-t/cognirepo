# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Behaviour tracker — records query-retrieval-edit chains and file co-occurrence
to build per-symbol usefulness weights for the hybrid retrieval scorer.

Persists to .cognirepo/graph/behaviour.json
"""
from __future__ import annotations

import hashlib
import json
import os
import re
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


# Prevention hints keyed on common error type substrings
_ERROR_HINTS: list[tuple[str, str]] = [
    ("NameError",      "Undefined variable — check imports and scope before use."),
    ("ImportError",    "Import failed — verify package is installed and module path is correct."),
    ("AttributeError", "Object missing attribute — check type, None-guard, or spelling."),
    ("TypeError",      "Wrong type — validate inputs at function boundary."),
    ("KeyError",       "Missing dict key — use .get() with default or check existence first."),
    ("IndexError",     "List out of range — guard with len() check before access."),
    ("ValueError",     "Invalid value — add input validation before processing."),
    ("SyntaxError",    "Syntax error — run a linter (ruff/flake8) before committing."),
    ("RuntimeError",   "Runtime failure — add error logging at the call site."),
    ("OSError",        "File/IO error — always guard file ops with try/except OSError."),
    ("Timeout",        "Timeout — add explicit timeout parameter and retry logic."),
    ("AssertionError", "Assertion failed — review invariants; do not use assert in prod."),
]


def _error_prevention_hint(error_type: str) -> str:
    """Return a short prevention tip based on the error type name."""
    for key, hint in _ERROR_HINTS:
        if key.lower() in error_type.lower():
            return hint
    return "Track root cause and add a targeted guard at the call site."


class BehaviourTracker:
    """
    Tracks developer and query behaviour to produce per-symbol hit counts
    used by HybridRetriever._behaviour_score_normalized().
    """

    # Number of queries to buffer before auto-summarising interaction style
    _STYLE_SUMMARIZE_EVERY = 10

    def __init__(self, graph: KnowledgeGraph, db_adapter=None) -> None:
        self.graph = graph
        self._db_adapter = db_adapter  # VectorStorageAdapter | None
        self.data: dict = {
            "version": 2,
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
                # Question type distribution: {type: count}
                "question_types": {},
                # Framing hints snapshot for Claude (rebuilt on summarize)
                "framing_hints": "",
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
        faiss_rows: list[int] | None = None,
    ) -> None:
        """
        Log a retrieval event. Adds QUERY node + QUERIED_WITH edges to graph.
        faiss_rows — parallel list of vector DB row indices for retrieved_symbols.
        """
        self.data["query_history"][query_id] = {
            "query_text": query_text,
            "timestamp": _now(),
            "retrieved_symbols": retrieved_symbols,
            "faiss_rows": faiss_rows or [],
            "useful": None,
        }

        # ── interaction style: buffer query text ─────────────────────────────
        style = self.data.setdefault("interaction_style", {
            "query_patterns": [], "terminology": {},
            "preferred_depth": "unknown", "last_summarized": None,
            "question_types": {}, "framing_hints": "",
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
        # question type detection
        q_lower = query_text.lower().strip()
        qtypes: dict = style.setdefault("question_types", {})
        _QTYPE_PATTERNS = [
            ("why",     r"^why\b"),
            ("what",    r"^what\b"),
            ("how",     r"^how\b"),
            ("fix",     r"^(fix|debug|resolve|solve|error|bug)\b"),
            ("explain", r"^(explain|describe|tell me about|what does)\b"),
            ("where",   r"^where\b"),
            ("refactor",r"^(refactor|improve|optimize|simplify|clean)\b"),
            ("add",     r"^(add|implement|create|write|build)\b"),
        ]
        for qtype, pattern in _QTYPE_PATTERNS:
            if re.search(pattern, q_lower):
                qtypes[qtype] = qtypes.get(qtype, 0) + 1
                break
        else:
            qtypes["other"] = qtypes.get("other", 0) + 1

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
            faiss_rows = qh.get("faiss_rows", [])
            for idx, sym in enumerate(qh.get("retrieved_symbols", [])):
                if sym not in sw:
                    sw[sym] = {"hit_count": 0, "last_hit": None, "relevance_feedback": 0.0}
                sw[sym]["hit_count"] += 1
                sw[sym]["last_hit"] = _now()
                new_score = min(1.0, sw[sym]["relevance_feedback"] + 0.1)
                sw[sym]["relevance_feedback"] = new_score
                # propagate score back into vector store
                if self._db_adapter is not None and idx < len(faiss_rows):
                    try:
                        self._db_adapter.update_behaviour_score(faiss_rows[idx], new_score)
                    except Exception:  # pylint: disable=broad-except
                        pass  # best-effort

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

    def record_error(
        self,
        error_type: str,
        file_path: str,
        message: str = "",
        query_context: str = "",
    ) -> None:
        """Log a syntax or runtime error with dedup signature and context."""
        ep = self.data["error_patterns"]
        if error_type not in ep:
            ep[error_type] = {
                "count": 0,
                "files": [],
                "last_seen": None,
                "signature": hashlib.md5(error_type.encode()).hexdigest()[:8],
                "occurrences": [],
                "prevention_hint": _error_prevention_hint(error_type),
            }
        ep[error_type]["count"] += 1
        ep[error_type]["last_seen"] = _now()
        if file_path and file_path not in ep[error_type]["files"]:
            ep[error_type]["files"].append(file_path)
        # Keep last 5 detailed occurrences for context
        occurrence = {"time": _now(), "file": file_path, "message": message[:300]}
        if query_context:
            occurrence["query"] = query_context[:200]
        occurrences: list = ep[error_type].setdefault("occurrences", [])
        occurrences.append(occurrence)
        if len(occurrences) > 5:
            occurrences.pop(0)

    # ── user profile ──────────────────────────────────────────────────────────

    def get_user_profile(self) -> dict:
        """Return a comprehensive user behavior profile for Claude framing.

        Includes: question types, depth preference, top terminology, framing hints.
        """
        style = self.data.get("interaction_style", {})
        qtypes: dict = style.get("question_types", {})
        terms: dict = style.get("terminology", {})
        patterns: list = style.get("query_patterns", [])
        depth = style.get("preferred_depth", "unknown")

        # Top question type
        top_qtype = max(qtypes, key=qtypes.get, default="unknown") if qtypes else "unknown"

        # Top 10 domain terms (exclude stopwords already filtered)
        top_terms = sorted(terms, key=lambda k: terms[k], reverse=True)[:10]

        # Infer code-focus: queries containing identifiers (snake_case or CamelCase)
        _ID_RE = re.compile(r'\b[a-z][a-z_]+[a-z]\b|[A-Z][a-zA-Z]+')
        code_queries = sum(1 for q in patterns if _ID_RE.search(q))
        code_focus_pct = round(100 * code_queries / max(len(patterns), 1))

        # Build framing hints string
        hints_parts = []
        if depth != "unknown":
            hints_parts.append(f"prefers {depth} responses")
        if top_qtype not in ("unknown", "other"):
            hints_parts.append(f"often asks '{top_qtype}' questions")
        if code_focus_pct > 60:
            hints_parts.append("focuses on code/symbols, not prose")
        if top_terms:
            hints_parts.append(f"domain vocabulary: {', '.join(top_terms[:5])}")

        framing_hints = "; ".join(hints_parts) if hints_parts else "no profile yet"

        sample_queries = patterns[-3:] if patterns else []

        return {
            "depth_preference": depth,
            "top_question_type": top_qtype,
            "question_type_distribution": qtypes,
            "top_terminology": top_terms,
            "code_focus_percent": code_focus_pct,
            "framing_hints": framing_hints,
            "sample_queries": sample_queries,
            "total_queries_tracked": len(self.data.get("query_history", {})),
        }

    # ── error patterns ────────────────────────────────────────────────────────

    def get_error_patterns(self, min_count: int = 1) -> list[dict]:
        """Return error patterns sorted by frequency, with prevention hints.

        min_count: only return patterns seen at least this many times.
        """
        ep = self.data.get("error_patterns", {})
        result = []
        for error_type, data in ep.items():
            if data.get("count", 0) < min_count:
                continue
            result.append({
                "error_type": error_type,
                "count": data.get("count", 0),
                "files": data.get("files", []),
                "last_seen": data.get("last_seen"),
                "signature": data.get("signature", ""),
                "prevention_hint": data.get(
                    "prevention_hint", _error_prevention_hint(error_type)
                ),
                "recent_context": (data.get("occurrences") or [{}])[-1].get("message", ""),
            })
        result.sort(key=lambda x: x["count"], reverse=True)
        return result

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
            qtypes: dict = style.get("question_types", {})
            top_qtype = max(qtypes, key=qtypes.get, default="N/A") if qtypes else "N/A"

            summary = (
                f"User interaction style: prefers {depth} answers. "
                f"Most common question type: {top_qtype}. "
                f"Common terminology: {', '.join(top_terms) if top_terms else 'N/A'}. "
                f"Recent query examples: {' | '.join(q[:80] for q in sample_queries)}."
            )
            store_memory(summary, source="interaction_style", importance=0.8)
            # Build framing hints snapshot for get_user_profile()
            hints_parts = []
            if depth != "unknown":
                hints_parts.append(f"prefers {depth} responses")
            if top_qtype not in ("N/A", "other"):
                hints_parts.append(f"often asks '{top_qtype}' questions")
            if top_terms:
                hints_parts.append(f"domain vocabulary: {', '.join(top_terms[:5])}")
            style["framing_hints"] = "; ".join(hints_parts)
            style["last_summarized"] = _now()
            # Clear buffer after summarising so next batch is fresh
            style["query_patterns"] = []
            style["terminology"] = {}
            return True
        except Exception:  # pylint: disable=broad-except
            return False  # always best-effort
