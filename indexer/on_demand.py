# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""
indexer/on_demand.py
On-access incremental graph expansion.

When an MCP tool (lookup_symbol, context_pack, who_calls) misses a symbol
and the file exists in the Tier 2 pending queue, this module immediately
indexes that file + its direct imports so the query can be retried live.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


def _load_queue(queue_path: str) -> dict:
    try:
        import filelock  # pylint: disable=import-outside-toplevel
        with filelock.FileLock(queue_path + ".lock", timeout=5):
            with open(queue_path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:  # pylint: disable=broad-except
        return {}


def _save_queue(queue_path: str, data: dict) -> None:
    try:
        import filelock  # pylint: disable=import-outside-toplevel
        with filelock.FileLock(queue_path + ".lock", timeout=10):
            with open(queue_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
    except Exception as exc:  # pylint: disable=broad-except
        log.warning("on_demand: failed to update queue: %s", exc)


def expand_on_access(rel_path: str, repo_root: str, indexer: "object") -> bool:
    """
    Immediately index rel_path if it is in the Tier 2 pending queue.
    Also indexes its direct Python imports (1 hop) to avoid follow-up misses.

    Returns True if anything was newly indexed and the caller should retry.
    Thread-safe via filelock on pending_tier2.json.
    """
    from config.paths import pending_tier2_path  # pylint: disable=import-outside-toplevel

    queue_path = pending_tier2_path()
    if not os.path.exists(queue_path):
        return False

    data = _load_queue(queue_path)
    pending_files: list[dict] = data.get("files", [])
    pending_map = {e["rel_path"]: e for e in pending_files}

    if rel_path not in pending_map:
        return False

    import warnings  # pylint: disable=import-outside-toplevel
    newly_indexed: list[str] = []

    def _do_index(entry: dict) -> None:
        rp = entry["rel_path"]
        ap = entry["abs_path"]
        w = entry.get("weight", 0.5)
        if not os.path.isfile(ap):
            return
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                indexer.index_file(rp, ap, weight=w)  # type: ignore[attr-defined]
            newly_indexed.append(rp)
            log.info("on_demand: indexed %s (weight=%.2f)", rp, w)
        except Exception as exc:  # pylint: disable=broad-except
            log.debug("on_demand: skip %s: %s", rp, exc)

    # Index the requested file
    _do_index(pending_map[rel_path])

    # Index its direct imports (1 hop) if they are also pending
    _imports = _extract_direct_imports(
        pending_map[rel_path]["abs_path"],
        repo_root,
    )
    for imp_rel in _imports:
        if imp_rel in pending_map:
            _do_index(pending_map[imp_rel])

    if not newly_indexed:
        return False

    # Persist: remove indexed files from queue
    remaining = [e for e in pending_files if e["rel_path"] not in newly_indexed]
    _save_queue(queue_path, {**data, "files": remaining})

    # Update AST index on disk
    try:
        indexer._build_reverse_index()  # type: ignore[attr-defined]
        indexer.save()  # type: ignore[attr-defined]
    except Exception as exc:  # pylint: disable=broad-except
        log.warning("on_demand: save failed: %s", exc)

    return True


def expand_on_access_for_symbol(symbol_name: str, repo_root: str, indexer: "object") -> bool:
    """
    Find candidate files in the Tier 2 queue that might contain symbol_name
    (by filename heuristic and grep), then index them via expand_on_access.

    Returns True if any file was indexed.
    """
    from config.paths import pending_tier2_path  # pylint: disable=import-outside-toplevel
    import subprocess  # pylint: disable=import-outside-toplevel

    queue_path = pending_tier2_path()
    if not os.path.exists(queue_path):
        return False

    data = _load_queue(queue_path)
    pending_files: list[dict] = data.get("files", [])
    if not pending_files:
        return False

    # Fast grep across pending file paths to find candidates
    candidates: list[str] = []
    for entry in pending_files:
        ap = entry["abs_path"]
        if not os.path.isfile(ap):
            continue
        # Filename heuristic: symbol name appears in file name (snake_case match)
        stem = Path(ap).stem.lower().replace("_", "")
        sym_lower = symbol_name.lower().replace("_", "")
        if sym_lower in stem or stem in sym_lower:
            candidates.append(entry["rel_path"])
            continue
        # Lightweight grep (no subprocess overhead for small files)
        try:
            with open(ap, encoding="utf-8", errors="replace") as _f:
                if symbol_name in _f.read():
                    candidates.append(entry["rel_path"])
        except OSError:
            pass
        if len(candidates) >= 3:
            break

    expanded = False
    for rel_path in candidates[:3]:
        if expand_on_access(rel_path, repo_root, indexer):
            expanded = True
    return expanded


def _extract_direct_imports(abs_path: str, repo_root: str) -> list[str]:
    """Parse Python imports from abs_path and return rel_paths within repo_root."""
    ext = Path(abs_path).suffix
    if ext not in (".py",):
        return []
    try:
        import ast as _ast  # pylint: disable=import-outside-toplevel
        with open(abs_path, encoding="utf-8", errors="replace") as f:
            source = f.read()
        tree = _ast.parse(source, filename=abs_path)
    except Exception:  # pylint: disable=broad-except
        return []

    imports: list[str] = []
    pkg_root = os.path.dirname(abs_path)

    for node in _ast.walk(tree):
        if isinstance(node, _ast.ImportFrom) and node.module:
            # Relative import: from . import X
            parts = node.module.split(".")
            candidate = os.path.join(pkg_root, *parts) + ".py"
            rel = os.path.relpath(candidate, repo_root)
            if os.path.isfile(candidate):
                imports.append(rel)
        elif isinstance(node, _ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                candidate = os.path.join(repo_root, *parts) + ".py"
                rel = os.path.relpath(candidate, repo_root)
                if os.path.isfile(candidate):
                    imports.append(rel)

    return imports[:10]  # cap at 10 to avoid expanding too aggressively
