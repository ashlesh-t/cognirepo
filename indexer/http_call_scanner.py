# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""
indexer/http_call_scanner.py
Outbound HTTP client call scanner + cross-service edge builder.

Scans source files for HTTP client calls (requests, httpx, axios, fetch, net/http),
matches URL patterns to registered endpoints in sibling services,
and adds function-level CALLS_API edges to the org graph.

Writes .cognirepo/index/http_calls.json.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# ── outbound HTTP call patterns ───────────────────────────────────────────────

# Python: requests/httpx/aiohttp — method(url_expr, ...)
_PY_HTTP = re.compile(
    r'(?:requests|httpx|aiohttp\.ClientSession\(\)|client|session)\s*\.\s*'
    r'(get|post|put|delete|patch|request)\s*\(\s*(?:f?["\']([^"\']+)["\']|(\w+))',
    re.IGNORECASE,
)

# JS/TS: fetch("/path") or axios.get("/path")
_JS_FETCH = re.compile(
    r'(?:fetch|axios\s*\.\s*(?:get|post|put|delete|patch))\s*\(\s*["`\']([^"`\']+)["`\']',
    re.IGNORECASE,
)

# Go: http.Get(url) or http.Post(url, ...)  where url contains a path literal
_GO_HTTP = re.compile(
    r'http\s*\.\s*(Get|Post|Put|Delete|Patch|NewRequest)\s*\(\s*(?:"([^"]+)"|(\w+\s*\+\s*"([^"]+)"))',
    re.IGNORECASE,
)

# URL path heuristic — skip base URLs like "https://example.com"
_PATH_RE = re.compile(r'^(/[a-zA-Z0-9_\-{}:]+)+')


def _extract_path(url: str) -> str | None:
    """Extract the path component from a URL or literal path."""
    url = url.strip()
    if url.startswith(("http://", "https://")):
        m = re.search(r'https?://[^/]+(/.+)', url)
        return m.group(1) if m else None
    if url.startswith("/"):
        return url.split("?")[0]
    return None


def _current_function(lines: list[str], line_idx: int) -> str:
    for i in range(line_idx, -1, -1):
        m = re.search(r'(?:def|func|function|const|async function)\s+(\w+)', lines[i])
        if m:
            return m.group(1)
    return "unknown"


def _scan_python_calls(source: str, rel_path: str) -> list[dict]:
    calls: list[dict] = []
    lines = source.splitlines()
    for i, line in enumerate(lines):
        m = _PY_HTTP.search(line)
        if not m:
            continue
        method = m.group(1)
        url_literal = m.group(2) or ""
        path = _extract_path(url_literal)
        if not path:
            continue
        calls.append({
            "caller_function": _current_function(lines, i),
            "caller_file": rel_path,
            "caller_line": i + 1,
            "url_pattern": path,
            "method": method.upper(),
            "client_library": "requests/httpx",
        })
    return calls


def _scan_js_calls(source: str, rel_path: str) -> list[dict]:
    calls: list[dict] = []
    lines = source.splitlines()
    for i, line in enumerate(lines):
        m = _JS_FETCH.search(line)
        if not m:
            continue
        path = _extract_path(m.group(1))
        if not path:
            continue
        method = "GET" if "fetch" in line[:m.start() + 10] else "POST"
        calls.append({
            "caller_function": _current_function(lines, i),
            "caller_file": rel_path,
            "caller_line": i + 1,
            "url_pattern": path,
            "method": method,
            "client_library": "fetch/axios",
        })
    return calls


def _scan_go_calls(source: str, rel_path: str) -> list[dict]:
    calls: list[dict] = []
    lines = source.splitlines()
    for i, line in enumerate(lines):
        m = _GO_HTTP.search(line)
        if not m:
            continue
        url_literal = m.group(2) or m.group(4) or ""
        path = _extract_path(url_literal)
        if not path:
            continue
        method = m.group(1).upper()
        calls.append({
            "caller_function": _current_function(lines, i),
            "caller_file": rel_path,
            "caller_line": i + 1,
            "url_pattern": path,
            "method": method if method in ("GET", "POST", "PUT", "DELETE", "PATCH") else "GET",
            "client_library": "net/http",
        })
    return calls


_CALL_SCANNER_MAP: dict[str, "callable"] = {
    ".py": _scan_python_calls,
    ".go": _scan_go_calls,
    ".js": _scan_js_calls,
    ".ts": _scan_js_calls,
    ".mjs": _scan_js_calls,
}


def _path_matches(call_pattern: str, endpoint_pattern: str) -> bool:
    """
    Fuzzy match between a caller URL literal and an endpoint path pattern.
    Handles path params: /users/123 matches /users/{id} or /users/:id.
    """
    # Normalise endpoint params: {id} or :id → wildcard segment
    norm = re.sub(r'\{[^}]+\}|:[a-zA-Z_]\w*', '[^/]+', endpoint_pattern)
    norm = norm.replace("*", ".*")
    try:
        return bool(re.fullmatch(norm.rstrip("/"), call_pattern.rstrip("/")))
    except re.error:
        return call_pattern.rstrip("/") == endpoint_pattern.rstrip("/")


def scan_http_calls(repo_root: str) -> dict:
    """
    Scan repo_root for outbound HTTP calls. Writes http_calls.json.
    Returns the calls dict.
    """
    from core.config.paths import http_calls_path  # pylint: disable=import-outside-toplevel

    all_calls: list[dict] = []
    repo_root = os.path.abspath(repo_root)

    _skip_dirs = {
        "node_modules", ".git", "__pycache__", "vendor", "dist",
        "build", ".cognirepo", "venv", ".venv",
    }

    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in _skip_dirs]
        for fname in filenames:
            ext = Path(fname).suffix
            if ext not in _CALL_SCANNER_MAP:
                continue
            abs_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(abs_path, repo_root)
            try:
                with open(abs_path, encoding="utf-8", errors="replace") as f:
                    source = f.read()
                calls = _CALL_SCANNER_MAP[ext](source, rel_path)
                all_calls.extend(calls)
            except Exception as exc:  # pylint: disable=broad-except
                log.debug("http_call_scanner: skip %s: %s", rel_path, exc)

    result = {
        "calls": all_calls,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": repo_root,
        "count": len(all_calls),
    }

    out_path = http_calls_path()
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
    except Exception as exc:  # pylint: disable=broad-except
        log.warning("http_call_scanner: failed to write: %s", exc)

    return result


def wire_cross_service_edges(
    caller_repo: str,
    sibling_repos: "list[str]",
    knowledge_graph: "object | None" = None,
) -> int:
    """
    Match this repo's outbound HTTP calls against endpoints in sibling services.
    For each match, adds a function-level CALLS_API edge to the org graph.
    Also adds CALLS_ENDPOINT edge to the local KG if knowledge_graph is provided.

    Returns number of edges added.
    """
    from core.config.paths import http_calls_path, endpoints_path  # pylint: disable=import-outside-toplevel
    from data.graph.org_graph import get_org_graph  # pylint: disable=import-outside-toplevel

    caller_repo = os.path.abspath(caller_repo)
    calls_file = http_calls_path()
    if not os.path.exists(calls_file):
        return 0
    with open(calls_file, encoding="utf-8") as f:
        calls_data = json.load(f)
    all_calls: list[dict] = calls_data.get("calls", [])
    if not all_calls:
        return 0

    og = get_org_graph()
    edges_added = 0

    for sib_repo in sibling_repos:
        sib_repo_abs = os.path.abspath(sib_repo)
        if sib_repo_abs == caller_repo:
            continue

        # Load sibling's endpoints.json
        from core.config.paths import _CTX_DIR, get_cognirepo_dir_for_repo  # pylint: disable=import-outside-toplevel
        sib_cognirepo = get_cognirepo_dir_for_repo(sib_repo_abs)
        sib_endpoints_file = os.path.join(sib_cognirepo, "index", "endpoints.json")
        if not os.path.exists(sib_endpoints_file):
            continue
        try:
            with open(sib_endpoints_file, encoding="utf-8") as f:
                sib_ep_data = json.load(f)
            sib_endpoints: list[dict] = sib_ep_data.get("endpoints", [])
        except Exception:  # pylint: disable=broad-except
            continue

        for call in all_calls:
            for ep in sib_endpoints:
                if not _path_matches(call["url_pattern"], ep["path_pattern"]):
                    continue
                if call["method"] not in (ep["method"], "ANY", "*"):
                    continue

                # Add function-level CALLS_API edge to org graph
                og.link(
                    src=caller_repo,
                    dst=sib_repo_abs,
                    kind="CALLS_API",
                    auto=True,
                    caller_fn=call["caller_function"],
                    caller_file=call["caller_file"],
                    endpoint_pattern=ep["path_pattern"],
                    endpoint_fn=ep["function"],
                )

                # Add CALLS_ENDPOINT edge to local KG
                if knowledge_graph is not None:
                    from data.graph.knowledge_graph import NodeType, EdgeType  # pylint: disable=import-outside-toplevel
                    from data.graph.graph_utils import make_node_id  # pylint: disable=import-outside-toplevel
                    caller_node = make_node_id("FUNCTION", call["caller_function"], call["caller_file"])
                    ep_node_id = f"endpoint::{sib_repo_abs}::{ep['method']}::{ep['path_pattern']}"
                    knowledge_graph.add_node(  # type: ignore[attr-defined]
                        ep_node_id, NodeType.ENDPOINT,
                        method=ep["method"], path_pattern=ep["path_pattern"],
                        handler=ep["function"], service=os.path.basename(sib_repo_abs),
                    )
                    knowledge_graph.add_edge(  # type: ignore[attr-defined]
                        caller_node, ep_node_id, EdgeType.CALLS_ENDPOINT,
                    )

                edges_added += 1
                log.info(
                    "wired: %s::%s → %s%s (%s::%s)",
                    os.path.basename(caller_repo), call["caller_function"],
                    os.path.basename(sib_repo_abs), ep["path_pattern"],
                    os.path.basename(sib_repo_abs), ep["function"],
                )

    if edges_added:
        og.save()
    return edges_added
