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
from typing import Any, Callable

from data.graph.knowledge_graph import KnowledgeGraph, NodeType, EdgeType
from data.graph.graph_utils import make_node_id

from core.config.paths import get_path

def _behaviour_file() -> str:
    return get_path("graph/behaviour.json")


def _behaviour_lock():
    """
    Cross-process/cross-thread file lock scoped to behaviour.json only.

    A dedicated lock (not core.config.lock.store_lock) avoids nesting with the
    vector-DB write lock acquired downstream by store_fn() during
    summarize_interaction_style() — see COGNIREPO-D09.
    """
    try:
        from filelock import FileLock  # pylint: disable=import-outside-toplevel
        return FileLock(_behaviour_file() + ".lock", timeout=15.0)
    except ImportError as exc:
        raise ImportError(
            "filelock is required for concurrent write safety. "
            "Run: pip install filelock"
        ) from exc


_USEFUL_WINDOW = timedelta(minutes=5)
_MOOD_FRUSTRATED_WINDOW = timedelta(minutes=15)
_MOOD_FRUSTRATED_ERROR_THRESHOLD = 3
_MOOD_FRUSTRATED_REWRITE_THRESHOLD = 2
_MOOD_FLOW_WINDOW = timedelta(minutes=20)

# Reserved "persona" preference values (COGNIREPO-402) — opt-in only, never auto-enabled.
# Each behavior delta must be concrete (retrieval depth / verbosity / tone), never decorative.
_PERSONAS: dict[str, dict[str, str]] = {
    "mentor": {
        "retrieval_depth": "+1 — include episodic context by default",
        "verbosity": "full explanations",
        "tone": "links responses to related past decisions/history",
    },
    "pair": {
        "retrieval_depth": "default",
        "verbosity": "default, plus mood-aware phrasing",
        "tone": "current default-equivalent behavior",
    },
    "caveman": {
        "retrieval_depth": "default",
        "verbosity": "economy output — see COGNIREPO-403 for the full spec",
        "tone": "telegraphic, complete-information style; opt-in only, never auto-enabled",
    },
}


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


_ACTIONABLE_INSTALL_PATTERNS = (
    "pip install", "pipx install", "npm install", "yarn add",
    "brew install", "apt install", "apt-get install", "conda install", "cargo install",
)


def _error_prevention_hint(error_type: str) -> str:
    """Return a short prevention tip based on the error type name."""
    for key, hint in _ERROR_HINTS:
        if key.lower() in error_type.lower():
            return hint
    return "Track root cause and add a targeted guard at the call site."


def _enrich_hint_from_context(generic_hint: str, recent_message: str) -> str:
    """Prepend an actionable command from the stored error message to the generic hint."""
    if not recent_message:
        return generic_hint
    for line in recent_message.splitlines():
        line_stripped = line.strip()
        if any(pat in line_stripped for pat in _ACTIONABLE_INSTALL_PATTERNS):
            return f"{line_stripped} — {generic_hint}"
    return generic_hint


class BehaviourTracker:
    """
    Tracks developer and query behaviour to produce per-symbol hit counts
    used by HybridRetriever._behaviour_score_normalized().
    """

    # Number of queries to buffer before auto-summarising interaction style
    _STYLE_SUMMARIZE_EVERY = 10

    def __init__(
        self,
        graph: KnowledgeGraph,
        db_adapter=None,
        *,
        store_fn: Callable[..., Any] | None = None,
    ) -> None:
        self.graph = graph
        self._db_adapter = db_adapter  # VectorStorageAdapter | None
        # Interface-layer callback for persisting interaction-style summaries as
        # semantic memory (interface.tools.store_memory.store_memory). Injected
        # by callers to keep this module free of upward `data → interface`
        # imports — see IMPROVEMENTS.md item 1 / COGNIREPO-105.
        self._store_fn = store_fn
        self.data: dict = {
            "version": 2,
            "updated_at": _now(),
            "symbol_weights": {},
            "query_history": {},
            "file_edit_cooccurrence": {},
            "error_patterns": {},
            "session_registry": {},
            "user_preferences": {},
            "query_rewrites": [],  # [{original, intent, context, stored_at, hit_count}]
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
        self._load()
        # Snapshot of interaction_style as of load time — used by save() to tell
        # apart "this instance's own new queries" from "another writer already
        # summarized and reset the ring buffer since we loaded" (COGNIREPO-D09).
        style = self.data.get("interaction_style", {})
        self._loaded_query_patterns: list = list(style.get("query_patterns", []))
        self._loaded_last_summarized = style.get("last_summarized")

    # ── persistence ───────────────────────────────────────────────────────────

    def _read_raw(self, path: str) -> dict | None:
        """Read+decrypt behaviour.json from disk without touching self.data."""
        if not os.path.exists(path):
            return None
        try:
            raw = open(path, "rb").read()
            try:
                from core.security.storage import get_storage_config  # pylint: disable=import-outside-toplevel
                encrypt, project_id = get_storage_config()
                if encrypt:
                    from core.security.encryption import get_or_create_key, decrypt_bytes  # pylint: disable=import-outside-toplevel
                    raw = decrypt_bytes(raw, get_or_create_key(project_id))
            except Exception:  # pylint: disable=broad-except
                pass  # encryption not configured — treat as plaintext
            return json.loads(raw)
        except (json.JSONDecodeError, OSError, ValueError):
            return None  # start fresh

    def _load(self) -> None:
        disk = self._read_raw(_behaviour_file())
        if disk is not None:
            self.data = disk

    def _merge_from_disk(self, disk: dict) -> None:
        """
        Additively fold concurrently-written disk state into self.data right
        before overwriting it, so a stale in-memory snapshot loaded by one
        request never clobbers another concurrent request's update.

        Fixes COGNIREPO-D09: parallel MCP tool calls each construct their own
        BehaviourTracker (load → mutate → save) with no synchronization; the
        last save() to run used to win outright, silently reverting whichever
        other call had just cleared query_patterns/set last_summarized inside
        summarize_interaction_style() — auto-summarization looked permanently
        stuck (query_patterns capped at 50, last_summarized never set) even
        though summarize_interaction_style() itself was fixed and working.
        """
        # query_history is keyed by a fresh uuid per query — union is always safe.
        disk_history = disk.get("query_history", {})
        history = self.data.setdefault("query_history", {})
        for qid, entry in disk_history.items():
            history.setdefault(qid, entry)

        # symbol_weights: keep whichever side saw the higher hit_count per symbol.
        disk_weights = disk.get("symbol_weights", {})
        weights = self.data.setdefault("symbol_weights", {})
        for sym, dv in disk_weights.items():
            wv = weights.get(sym)
            if wv is None or dv.get("hit_count", 0) > wv.get("hit_count", 0):
                weights[sym] = dv

        # interaction_style: if disk was summarized more recently than what this
        # instance loaded, another writer already reset the ring buffer — adopt
        # disk's post-summarize state and replay only the query text(s) *this*
        # instance appended since its own load (so they aren't lost).
        disk_style = disk.get("interaction_style", {})
        my_style = self.data.setdefault("interaction_style", {})
        disk_summarized = disk_style.get("last_summarized")
        if disk_summarized and disk_summarized != self._loaded_last_summarized:
            appended = my_style.get("query_patterns", [])[len(self._loaded_query_patterns):]
            my_style["query_patterns"] = disk_style.get("query_patterns", []) + appended
            my_style["terminology"] = disk_style.get("terminology", {})
            my_style["question_types"] = disk_style.get("question_types", {})
            my_style["preferred_depth"] = disk_style.get("preferred_depth", my_style.get("preferred_depth"))
            my_style["framing_hints"] = disk_style.get("framing_hints", my_style.get("framing_hints"))
            my_style["last_summarized"] = disk_summarized

    def save(self) -> None:
        """Persist behaviour data; encrypts if encryption is configured.

        Re-reads and merges concurrent on-disk state under a dedicated file
        lock (see _merge_from_disk) so parallel MCP tool calls don't lose each
        other's query_history/interaction_style updates — COGNIREPO-D09.
        """
        path = _behaviour_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with _behaviour_lock():
            disk = self._read_raw(path)
            if disk is not None:
                self._merge_from_disk(disk)
            self.data["updated_at"] = _now()
            raw = json.dumps(self.data, indent=2).encode()
            try:
                from core.security.storage import get_storage_config  # pylint: disable=import-outside-toplevel
                encrypt, project_id = get_storage_config()
                if encrypt:
                    from core.security.encryption import get_or_create_key, encrypt_bytes  # pylint: disable=import-outside-toplevel
                    raw = encrypt_bytes(raw, get_or_create_key(project_id))
            except Exception:  # pylint: disable=broad-except
                pass  # best-effort encryption
            with open(path, "wb") as f:
                f.write(raw)

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

        # auto-summarize interaction style every N queries
        if len(patterns) % self._STYLE_SUMMARIZE_EVERY == 0 and patterns:
            self.summarize_interaction_style()

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
                old_score = sw[sym]["relevance_feedback"]
                new_score = min(1.0, old_score * 0.95 + 0.1)
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
                "signature": hashlib.md5(error_type.encode(), usedforsecurity=False).hexdigest()[:8],  # nosec B324
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

        # Use cached snapshot when patterns were cleared after summarization
        framing_hints = (
            "; ".join(hints_parts)
            if hints_parts
            else style.get("framing_hints") or "no profile yet"
        )

        sample_queries = patterns[-3:] if patterns else []
        explicit_preferences = self.get_preferences()

        profile = {
            "depth_preference": depth,
            "top_question_type": top_qtype,
            "question_type_distribution": qtypes,
            "top_terminology": top_terms,
            "code_focus_percent": code_focus_pct,
            "framing_hints": framing_hints,
            "sample_queries": sample_queries,
            "total_queries_tracked": len(self.data.get("query_history", {})),
            "explicit_preferences": explicit_preferences,
            "query_rewrites": self.get_query_rewrites(),
            "mood": self.derive_mood(),
        }
        # Additive only — no persona set (or an already-rejected/unknown value that somehow
        # made it into storage before this validation existed) leaves the payload identical
        # to pre-402 output (COGNIREPO-402 AC2).
        active_persona = explicit_preferences.get("persona")
        if active_persona in _PERSONAS:
            profile["active_persona"] = active_persona
            profile["persona_behavior"] = _PERSONAS[active_persona]
        return profile

    def derive_mood(self) -> dict:
        """Derive a lightweight mood signal from existing behaviour data.

        state: "frustrated" | "flow" | "neutral". Never a bare sentiment label —
        suggested_adaptation is always an action Claude can take, not a tone
        adjective (COGNIREPO-401 AC4). Sparse/fresh data degrades to neutral with
        empty evidence, mirroring get_user_profile's "no profile yet" fallback.

        Derived within a recent time window (not all-time counts) so mood tracks
        the current session rather than pinning permanently on old errors.
        """
        now = datetime.now(tz=timezone.utc)

        def _recent(ts: str | None, window: timedelta) -> bool:
            if not ts:
                return False
            try:
                parsed = datetime.fromisoformat(ts)
            except ValueError:
                return False
            return now - parsed <= window

        # ── frustrated: error streak or a rewrite correction still recurring ──
        evidence: list[str] = []
        for error_type, info in self.data.get("error_patterns", {}).items():
            recent_occ = [
                occ for occ in info.get("occurrences", [])
                if _recent(occ.get("time"), _MOOD_FRUSTRATED_WINDOW)
            ]
            if len(recent_occ) >= _MOOD_FRUSTRATED_ERROR_THRESHOLD:
                evidence.append(f"{error_type}: {len(recent_occ)} occurrences in the last 15m")
        for rw in self.data.get("query_rewrites", []):
            if rw.get("hit_count", 0) >= _MOOD_FRUSTRATED_REWRITE_THRESHOLD and _recent(
                rw.get("updated_at") or rw.get("stored_at"), _MOOD_FRUSTRATED_WINDOW
            ):
                evidence.append(
                    f"query rewrite '{rw.get('original', '')[:40]}' re-corrected "
                    f"{rw.get('hit_count')}x"
                )
        if evidence:
            return {
                "state": "frustrated",
                "evidence": evidence,
                "suggested_adaptation": "verify against get_error_patterns before proposing fixes",
            }

        # ── flow: sustained queries + edits with zero new errors ─────────────
        recent_queries = [
            qh for qh in self.data.get("query_history", {}).values()
            if _recent(qh.get("timestamp"), _MOOD_FLOW_WINDOW)
        ]
        recent_edits = any(
            _recent(session.get("start"), _MOOD_FLOW_WINDOW) and session.get("files_touched")
            for session in self.data.get("session_registry", {}).values()
        )
        recent_errors = any(
            _recent(occ.get("time"), _MOOD_FLOW_WINDOW)
            for info in self.data.get("error_patterns", {}).values()
            for occ in info.get("occurrences", [])
        )
        if recent_queries and recent_edits and not recent_errors:
            return {
                "state": "flow",
                "evidence": [
                    f"{len(recent_queries)} queries and active edits over the last 20m "
                    f"with 0 new errors"
                ],
                "suggested_adaptation": "batch confirmations; skip re-explaining settled context",
            }

        return {"state": "neutral", "evidence": [], "suggested_adaptation": ""}

    def record_user_preference(self, key: str, value: str) -> dict:
        """Store an explicit user preference (key/value pair) with timestamp.

        Persisted immediately. Surfaced by get_user_profile()['explicit_preferences'].
        The reserved "persona" key is validated against _PERSONAS — an unknown value is
        rejected (not stored) so a typo doesn't silently no-op the opt-in.
        """
        if key == "persona" and value not in _PERSONAS:
            return {
                "key": key, "value": value, "recorded": False,
                "error": f"unknown persona '{value}' — valid: {sorted(_PERSONAS)}",
            }
        prefs = self.data.setdefault("user_preferences", {})
        prefs[key] = {"value": value, "updated_at": _now()}
        self.save()
        return {"key": key, "value": value, "recorded": True}

    def get_preferences(self) -> dict:
        """Return {key: value} for all stored user preferences (latest values only)."""
        raw = self.data.get("user_preferences", {})
        return {k: v["value"] for k, v in raw.items() if isinstance(v, dict)}

    def record_query_rewrite(self, original: str, intent: str, context: str = "") -> dict:
        """
        Store a query-rewrite correction: when user said X but meant Y.
        Future get_user_profile() surfaces these so agents apply them before retrieval.
        hit_count is incremented each time a matching query is seen.
        """
        rewrites: list = self.data.setdefault("query_rewrites", [])
        # Check if same original already stored — update rather than duplicate
        for rw in rewrites:
            if rw.get("original", "").lower() == original.lower():
                rw["intent"] = intent
                rw["context"] = context
                rw["updated_at"] = _now()
                self.save()
                return {"stored": True, "updated_existing": True, "original": original, "intent": intent}
        rewrites.append({
            "original": original,
            "intent": intent,
            "context": context,
            "stored_at": _now(),
            "hit_count": 0,
        })
        # Cap at 100 rewrites; drop oldest
        if len(rewrites) > 100:
            rewrites.pop(0)
        self.save()
        return {"stored": True, "updated_existing": False, "original": original, "intent": intent}

    def get_query_rewrites(self) -> list[dict]:
        """Return stored query-rewrite corrections sorted by hit_count desc."""
        rewrites = self.data.get("query_rewrites", [])
        return sorted(rewrites, key=lambda r: r.get("hit_count", 0), reverse=True)

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
            recent_msg = (data.get("occurrences") or [{}])[-1].get("message", "")
            generic_hint = data.get("prevention_hint", _error_prevention_hint(error_type))
            enriched_hint = _enrich_hint_from_context(generic_hint, recent_msg)
            entry = {
                "error_type": error_type,
                "count": data.get("count", 0),
                "files": data.get("files", []),
                "last_seen": data.get("last_seen"),
                "signature": data.get("signature", ""),
                "prevention_hint": enriched_hint,
                "recent_context": recent_msg,
            }
            # Structured split — the concatenated enriched_hint reads as a
            # run-on sentence; agents can use these fields directly instead.
            if enriched_hint != generic_hint:
                entry["suggested_command"] = enriched_hint.rsplit(" — ", 1)[0]
                entry["generic_hint"] = generic_hint
            result.append(entry)
        result.sort(key=lambda x: x["count"], reverse=True)
        return result

    # ── score access ──────────────────────────────────────────────────────────

    def get_hot_symbols(self, top_k: int = 10) -> list[dict]:
        """Return top_k symbols by hit_count, sorted descending."""
        weights = self.data.get("symbol_weights", {})
        scored = [
            {"symbol_id": sid, "name": sid.split("::")[-1], "hit_count": int(v.get("hit_count", 0))}
            for sid, v in weights.items()
            if isinstance(v, dict)
        ]
        scored.sort(key=lambda x: x["hit_count"], reverse=True)
        return scored[:top_k]

    def get_behaviour_score(self, symbol_id: str) -> float:
        """Raw hit_count for symbol_id; 0.0 if unseen."""
        return float(self.data["symbol_weights"].get(symbol_id, {}).get("hit_count", 0))

    def get_all_scores(self) -> dict[str, float]:
        """Returns {symbol_id: hit_count} for all tracked symbols."""
        return {k: float(v["hit_count"]) for k, v in self.data["symbol_weights"].items()}

    # ── interaction style summariser ──────────────────────────────────────────

    def summarize_interaction_style(self) -> bool:
        """
        When query_patterns buffer reaches _STYLE_SUMMARIZE_EVERY entries,
        build a natural-language summary and store it as a semantic memory
        with source="interaction_style" (importance is computed internally by
        store_memory() via SemanticMemory.compute_importance()).

        Returns True if a memory was stored, False otherwise.
        """
        style = self.data.get("interaction_style", {})
        patterns: list = style.get("query_patterns", [])
        if len(patterns) < self._STYLE_SUMMARIZE_EVERY:
            return False
        if self._store_fn is None:
            return False  # no interface-layer store callback injected — best-effort no-op

        try:
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
            self._store_fn(summary, source="interaction_style")
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
