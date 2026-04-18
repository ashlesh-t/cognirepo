# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Seed the CogniRepo behaviour tracker and learning store from git log.

Parses `git log --name-only` for the last 100 commits and pre-populates
per-symbol hit counts proportional to recency:
  - committed within last  7 days  → weight 1.0
  - committed within last 30 days  → weight 0.5
  - older (within last 100 commits) → weight 0.1

Also parses commit messages for:
  - fix: / revert: / decision: / breaking: / feat: prefixes → learning store
  - ADR files in docs/decisions/, docs/adr/, DECISIONS.md
  - Inline # FIXME, # HACK, # NOTE: comments from source files

Fail-silent if not in a git repo or git is unavailable.
Idempotent — skips if behaviour tracker already has symbol data.
"""
from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


_WEIGHT_7D  = 1.0
_WEIGHT_30D = 0.5
_WEIGHT_OLD = 0.1

# Commit message prefixes that map to learning types
_COMMIT_PREFIX_MAP = {
    "fix:":      "bug",
    "revert:":   "bug",
    "decision:": "decision",
    "breaking:": "prod_issue",
    "feat:":     "decision",
    "perf:":     "decision",
    "security:": "prod_issue",
    "hotfix:":   "prod_issue",
}

# Inline comment patterns that get seeded as learnings
_INLINE_COMMENT_RE = re.compile(
    r"#\s*(FIXME|HACK|NOTE|TODO|XXX|BUG|WARNING)[:\s]+(.{10,200})",
    re.IGNORECASE,
)
_INLINE_TYPE_MAP = {
    "fixme": "bug", "bug": "bug",
    "hack": "quirk", "warning": "quirk",
    "note": "decision", "todo": "decision",
    "xxx": "bug",
}


def _seed_commit_messages(repo_root: str, dry_run: bool = False) -> int:
    """
    Parse git log commit messages for typed prefixes and store as learnings.
    Returns number of learnings stored.
    """
    abs_root = os.path.abspath(repo_root)
    try:
        proc = subprocess.run(  # nosec B603
            ["git", "-C", abs_root, "log", "--pretty=format:%aI|%s|%b", "-n", "200"],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0
    if proc.returncode != 0:
        return 0

    try:
        from memory.learning_store import get_learning_store  # pylint: disable=import-outside-toplevel
        store = get_learning_store()
    except Exception:  # pylint: disable=broad-except
        return 0

    stored = 0
    now = datetime.now(tz=timezone.utc)

    for raw_line in proc.stdout.splitlines():
        if not raw_line.strip():
            continue
        parts = raw_line.split("|", 2)
        if len(parts) < 2:
            continue
        date_str, subject = parts[0], parts[1]
        body = parts[2] if len(parts) > 2 else ""

        subject = subject.strip()
        if not subject:
            continue

        # Match prefix
        subject_lower = subject.lower()
        learning_type = None
        for prefix, ltype in _COMMIT_PREFIX_MAP.items():
            if subject_lower.startswith(prefix):
                learning_type = ltype
                subject = subject[len(prefix):].strip()
                break

        if not learning_type:
            # Also capture commit messages that mention "broke", "fixed", "regression"
            if re.search(r"\b(broke|regression|critical|security|hotfix|revert)\b",
                         subject_lower, re.IGNORECASE):
                learning_type = "prod_issue"
            else:
                continue

        text = subject
        if body.strip():
            text += f"\n{body.strip()[:300]}"

        if len(text) < 10:
            continue

        try:
            # Parse date for context
            dt = datetime.fromisoformat(date_str)
            days_ago = (now - dt.replace(tzinfo=timezone.utc)).days if dt.tzinfo else 0
            context_summary = f"from git commit {days_ago}d ago"
        except ValueError:
            context_summary = "from git commit history"

        if not dry_run:
            try:
                store.store_learning(
                    learning_type=learning_type,
                    text=text[:500],
                    context_summary=context_summary,
                    tags=["git-seeded"],
                )
                stored += 1
            except Exception:  # pylint: disable=broad-except
                pass

    return stored


def _seed_adr_files(repo_root: str, dry_run: bool = False) -> int:
    """
    Parse ADR (Architecture Decision Record) files and store as decision learnings.
    Looks in docs/decisions/, docs/adr/, DECISIONS.md, ADR.md.
    Returns number of learnings stored.
    """
    abs_root = Path(os.path.abspath(repo_root))
    adr_locations = [
        abs_root / "docs" / "decisions",
        abs_root / "docs" / "adr",
        abs_root / "decisions",
    ]
    adr_files = []
    for loc in adr_locations:
        if loc.is_dir():
            adr_files.extend(sorted(loc.glob("*.md"))[:20])
    for name in ("DECISIONS.md", "ADR.md", "ARCHITECTURE_DECISIONS.md"):
        p = abs_root / name
        if p.is_file():
            adr_files.append(p)

    if not adr_files:
        return 0

    try:
        from memory.learning_store import get_learning_store  # pylint: disable=import-outside-toplevel
        store = get_learning_store()
    except Exception:  # pylint: disable=broad-except
        return 0

    stored = 0
    for adr_file in adr_files:
        try:
            text = adr_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Split into sections
        sections = re.split(r'\n(?=#{1,3} )', text)
        for section in sections:
            section = section.strip()
            if len(section) < 80:
                continue
            if not dry_run:
                try:
                    store.store_learning(
                        learning_type="decision",
                        text=section[:1000],
                        context_summary=f"from ADR {adr_file.name}",
                        tags=["adr-seeded", adr_file.stem.lower()],
                    )
                    stored += 1
                except Exception:  # pylint: disable=broad-except
                    pass
    return stored


def _seed_inline_comments(repo_root: str, dry_run: bool = False) -> int:
    """
    Scan source files for FIXME/HACK/NOTE/TODO inline comments and store as learnings.
    Returns number of learnings stored.
    """
    abs_root = Path(os.path.abspath(repo_root))
    _SKIP = frozenset({".git", "venv", ".venv", "node_modules", "__pycache__",
                       ".cognirepo", "dist", "build"})

    try:
        from memory.learning_store import get_learning_store  # pylint: disable=import-outside-toplevel
        store = get_learning_store()
    except Exception:  # pylint: disable=broad-except
        return 0

    stored = 0
    _SRC_EXTS = frozenset({".py", ".js", ".ts", ".java", ".go", ".rs", ".cpp", ".c"})

    for dirpath, dirnames, filenames in os.walk(abs_root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP]
        for fname in filenames:
            if Path(fname).suffix not in _SRC_EXTS:
                continue
            fpath = Path(dirpath) / fname
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(content.splitlines(), 1):
                m = _INLINE_COMMENT_RE.search(line)
                if not m:
                    continue
                tag, comment = m.group(1).upper(), m.group(2).strip()
                ltype = _INLINE_TYPE_MAP.get(tag.lower(), "bug")
                rel_path = str(fpath.relative_to(abs_root))
                text = f"{tag} in {rel_path}:{lineno}: {comment}"
                if not dry_run:
                    try:
                        store.store_learning(
                            learning_type=ltype,
                            text=text[:400],
                            context_summary=f"inline comment {rel_path}:{lineno}",
                            tags=["inline-comment", tag.lower()],
                        )
                        stored += 1
                    except Exception:  # pylint: disable=broad-except
                        pass
    return stored


def seed_from_git_log(
    repo_root: str = ".",
    dry_run: bool = False,
    tracker=None,
    indexer=None,
    seed_learnings: bool = True,
    seed_adrs: bool = True,
    seed_comments: bool = False,
) -> dict:
    """
    Seed behaviour weights from recent git history.
    """
    # pylint: disable=too-many-locals, too-many-branches
    # ── 1. resolve tracker ────────────────────────────────────────────────────
    if tracker is None:
        from graph.knowledge_graph import KnowledgeGraph        # pylint: disable=import-outside-toplevel
        from graph.behaviour_tracker import BehaviourTracker    # pylint: disable=import-outside-toplevel
        tracker = BehaviourTracker(graph=KnowledgeGraph())

    # idempotent guard
    if tracker.data.get("symbol_weights"):
        return {"skipped": "already seeded"}

    # ── 2. parse git log ──────────────────────────────────────────────────────
    abs_root = os.path.abspath(repo_root)
    try:
        proc = subprocess.run(  # nosec B603
            ["git", "-C", abs_root, "log", "--name-only",
             "--pretty=format:%aI", "-n", "100"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"skipped": "git not available"}

    if proc.returncode != 0:
        return {"skipped": "not a git repo"}

    # ── 3. collect file → max_weight mapping ─────────────────────────────────
    now = datetime.now(tz=timezone.utc)
    file_weights: dict[str, float] = {}
    current_date: datetime | None = None

    for raw_line in proc.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            dt = datetime.fromisoformat(line)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            current_date = dt
        except ValueError:
            if current_date is None:
                continue
            days_ago = (now - current_date).days
            if days_ago <= 7:
                w = _WEIGHT_7D
            elif days_ago <= 30:
                w = _WEIGHT_30D
            else:
                w = _WEIGHT_OLD
            if line not in file_weights or file_weights[line] < w:
                file_weights[line] = w

    if not file_weights:
        return {"seeded": 0}

    # ── 4. resolve symbols from AST index ────────────────────────────────────
    if indexer is None:
        from graph.knowledge_graph import KnowledgeGraph    # pylint: disable=import-outside-toplevel
        from indexer.ast_indexer import ASTIndexer          # pylint: disable=import-outside-toplevel
        indexer = ASTIndexer(graph=tracker.graph if hasattr(tracker, "graph") else KnowledgeGraph())
        indexer.load()

    seeds: list[tuple[str, float]] = []

    for file_path, weight in file_weights.items():
        file_data = indexer.index_data.get("files", {}).get(file_path, {})
        symbols = file_data.get("symbols", [])

        if symbols:
            for sym in symbols:
                node_id = f"{file_path}::{sym['name']}"
                seeds.append((node_id, weight))
        else:
            # no AST data — seed the file path as a fallback key
            seeds.append((file_path, weight))

    if dry_run:
        for node_id, weight in seeds:
            print(f"  would seed  {node_id}: {weight}")
        return {"would_seed": len(seeds)}

    # ── 5. write weights ──────────────────────────────────────────────────────
    sw = tracker.data.setdefault("symbol_weights", {})
    now_iso = now.isoformat()
    for node_id, weight in seeds:
        if node_id not in sw:
            sw[node_id] = {"hit_count": 0.0, "last_hit": None, "relevance_feedback": 0.0}
        # take max weight across all commits that touched this symbol
        sw[node_id]["hit_count"] = max(sw[node_id]["hit_count"], weight)
        sw[node_id]["last_hit"] = now_iso

    tracker.save()

    result: dict = {"seeded": len(seeds)}

    # ── I3: seed learning store from commit messages, ADRs, inline comments ────
    abs_root = os.path.abspath(repo_root)
    if seed_learnings:
        n_commits = _seed_commit_messages(abs_root, dry_run=dry_run)
        result["learnings_from_commits"] = n_commits
    if seed_adrs:
        n_adrs = _seed_adr_files(abs_root, dry_run=dry_run)
        result["learnings_from_adrs"] = n_adrs
    if seed_comments:
        n_comments = _seed_inline_comments(abs_root, dry_run=dry_run)
        result["learnings_from_comments"] = n_comments

    return result


# ── post-session auto-seed ─────────────────────────────────────────────────────

def seed_from_session(session_id: str | None = None) -> dict:
    """
    Called automatically at REPL exit (via atexit). Reads the last session from
    .cognirepo/sessions/ and stores any high-importance exchanges that weren't
    already auto-stored by AutoStore during the session.

    Returns: {"seeded": int} — number of memories stored, or {} on any error.
    """
    try:
        import json as _json   # pylint: disable=import-outside-toplevel
        from pathlib import Path as _Path  # pylint: disable=import-outside-toplevel
        from config.paths import get_path  # pylint: disable=import-outside-toplevel
        from tools.store_memory import store_memory  # pylint: disable=import-outside-toplevel

        sessions_dir = _Path(get_path("sessions"))
        if not sessions_dir.exists():
            return {}

        # Locate session file
        session_file: _Path | None = None
        if session_id:
            candidate = sessions_dir / f"{session_id}.json"
            if candidate.exists():
                session_file = candidate
        if session_file is None:
            # Fall back to most-recently modified session file
            candidates = sorted(sessions_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
            if candidates:
                session_file = candidates[-1]
        if session_file is None:
            return {}

        with open(session_file, encoding="utf-8") as f:
            session = _json.load(f)

        messages = session.get("messages", [])
        seeded = 0
        # Extract assistant turns that look like decisions/fixes/explanations
        _importance_patterns = re.compile(
            r"\b(fix(?:ed)?|bug|root cause|decision|should|must|never|always|"
            r"warning|important|critical|resolved|workaround|approach)\b",
            re.IGNORECASE,
        )
        for i, msg in enumerate(messages):
            if msg.get("role") != "assistant":
                continue
            text = msg.get("content", "")
            if len(text) < 80:
                continue
            if not _importance_patterns.search(text):
                continue
            # Prepend user question for context
            user_q = ""
            if i > 0 and messages[i - 1].get("role") == "user":
                user_q = messages[i - 1].get("content", "")[:120]
            memory_text = f"[session] Q: {user_q}\nA: {text[:600]}" if user_q else text[:600]
            try:
                store_memory(memory_text, source="session_seed", importance=0.6)
                seeded += 1
            except Exception:  # pylint: disable=broad-except
                pass

        return {"seeded": seeded}
    except Exception:  # pylint: disable=broad-except
        return {}  # always best-effort
