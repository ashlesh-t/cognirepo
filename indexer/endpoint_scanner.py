# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""
indexer/endpoint_scanner.py
HTTP endpoint registry — scans source files for route decorators/registrations
and writes .cognirepo/index/endpoints.json.

Supported:
  Python  — FastAPI (@router.get/post/put/delete/patch), Flask (@app.route),
             Django (path(), re_path() in urls.py)
  Go      — Gin (r.GET/POST/...), Chi/mux (r.Get/Post/...)
  JS/TS   — Express (app.get/post/...), Fastify (fastify.get/post/...)
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# ── regex patterns per language/framework ─────────────────────────────────────

# Python: @router.get("/path") or @app.route("/path", methods=["GET"])
_PY_FASTAPI = re.compile(
    r'@\w+\.(get|post|put|delete|patch|head|options)\(\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_PY_FLASK = re.compile(
    r'@\w+\.route\(\s*["\']([^"\']+)["\'](?:.*?methods\s*=\s*\[([^\]]+)\])?',
    re.DOTALL | re.IGNORECASE,
)
# Django: path("users/<int:id>/", view_func, name="...")
_PY_DJANGO = re.compile(
    r'(?:path|re_path)\(\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)

# Go: r.GET("/users/:id", handler) or router.Get("/users/{id}", handler)
_GO_ROUTER = re.compile(
    r'\.\s*(GET|POST|PUT|DELETE|PATCH|Head|Options|Handle)\(\s*"([^"]+)"',
    re.IGNORECASE,
)

# JS/TS: app.get("/path", handler) or fastify.get("/path", handler)
_JS_EXPRESS = re.compile(
    r'\.\s*(get|post|put|delete|patch)\(\s*["`\']([^"`\']+)["`\']',
    re.IGNORECASE,
)


def _normalize_method(raw: str) -> str:
    return raw.upper().strip() if raw else "GET"


def _detect_framework(lines: list[str], ext: str) -> str:
    joined = " ".join(lines[:50])
    if ext == ".py":
        if "fastapi" in joined.lower():
            return "fastapi"
        if "flask" in joined.lower():
            return "flask"
        if "django" in joined.lower() or "urlpatterns" in joined.lower():
            return "django"
        return "python"
    if ext == ".go":
        if "gin" in joined.lower():
            return "gin"
        if "chi" in joined.lower():
            return "chi"
        return "go"
    if ext in (".js", ".ts", ".mjs", ".cjs"):
        if "fastify" in joined.lower():
            return "fastify"
        return "express"
    return "unknown"


def _scan_python(source: str, rel_path: str) -> list[dict]:
    endpoints: list[dict] = []
    lines = source.splitlines()
    framework = _detect_framework(lines, ".py")

    for i, line in enumerate(lines, 1):
        # FastAPI / Flask decorator style
        m = _PY_FASTAPI.search(line)
        if m:
            method, path_pattern = m.group(1), m.group(2)
            # Next non-decorator line is likely the function def
            fn_name = _next_fn_name(lines, i)
            endpoints.append({
                "method": _normalize_method(method),
                "path_pattern": path_pattern,
                "function": fn_name,
                "file": rel_path,
                "line": i,
                "framework": framework,
            })
            continue

        m = _PY_FLASK.search(line)
        if m:
            path_pattern = m.group(1)
            methods_raw = m.group(2) or "GET"
            methods = [x.strip().strip("\"'") for x in methods_raw.split(",")]
            fn_name = _next_fn_name(lines, i)
            for method in methods:
                endpoints.append({
                    "method": _normalize_method(method),
                    "path_pattern": path_pattern,
                    "function": fn_name,
                    "file": rel_path,
                    "line": i,
                    "framework": "flask",
                })
            continue

        if "urls.py" in rel_path or "url_patterns" in source[:500]:
            m = _PY_DJANGO.search(line)
            if m:
                path_pattern = m.group(1)
                fn_name = _extract_django_view(line)
                endpoints.append({
                    "method": "ANY",
                    "path_pattern": path_pattern,
                    "function": fn_name,
                    "file": rel_path,
                    "line": i,
                    "framework": "django",
                })

    return endpoints


def _scan_go(source: str, rel_path: str) -> list[dict]:
    endpoints: list[dict] = []
    lines = source.splitlines()
    framework = _detect_framework(lines, ".go")

    for i, line in enumerate(lines, 1):
        m = _GO_ROUTER.search(line)
        if m:
            method, path_pattern = m.group(1), m.group(2)
            # Handler is the last identifier before closing paren
            fn_name = _extract_go_handler(line)
            endpoints.append({
                "method": _normalize_method(method),
                "path_pattern": path_pattern,
                "function": fn_name,
                "file": rel_path,
                "line": i,
                "framework": framework,
            })
    return endpoints


def _scan_js(source: str, rel_path: str) -> list[dict]:
    endpoints: list[dict] = []
    lines = source.splitlines()
    framework = _detect_framework(lines, Path(rel_path).suffix)

    for i, line in enumerate(lines, 1):
        m = _JS_EXPRESS.search(line)
        if m:
            method, path_pattern = m.group(1), m.group(2)
            fn_name = _extract_js_handler(line)
            endpoints.append({
                "method": _normalize_method(method),
                "path_pattern": path_pattern,
                "function": fn_name,
                "file": rel_path,
                "line": i,
                "framework": framework,
            })
    return endpoints


def _next_fn_name(lines: list[str], after_line: int) -> str:
    for line in lines[after_line:after_line + 5]:
        m = re.search(r'def\s+(\w+)', line)
        if m:
            return m.group(1)
    return "unknown"


def _extract_django_view(line: str) -> str:
    m = re.search(r',\s*(\w+)', line)
    return m.group(1) if m else "unknown"


def _extract_go_handler(line: str) -> str:
    # Last identifier-like token before ) is usually the handler
    tokens = re.findall(r'\b(\w+)\b', line)
    return tokens[-1] if tokens else "unknown"


def _extract_js_handler(line: str) -> str:
    # Look for arrow fn or named fn reference: app.get("/path", handler)
    m = re.search(r',\s*(?:async\s+)?(\w+)\s*(?:\)|=>)', line)
    return m.group(1) if m else "unknown"


_SCANNER_MAP: dict[str, "callable"] = {
    ".py": _scan_python,
    ".go": _scan_go,
    ".js": _scan_js,
    ".ts": _scan_js,
    ".mjs": _scan_js,
    ".cjs": _scan_js,
}

_ROUTE_FILE_HINTS = {"route", "router", "api", "handler", "view", "endpoint", "urls", "server", "main"}


def scan_endpoints(repo_root: str) -> dict:
    """
    Scan repo_root for HTTP route registrations. Writes endpoints.json.
    Returns the endpoints dict.
    """
    from config.paths import endpoints_path  # pylint: disable=import-outside-toplevel

    all_endpoints: list[dict] = []
    repo_root = os.path.abspath(repo_root)

    _skip_dirs = {
        "node_modules", ".git", "__pycache__", "vendor", "dist", "build",
        ".cognirepo", "venv", ".venv", "test", "tests", "spec",
    }

    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in _skip_dirs]
        for fname in filenames:
            ext = Path(fname).suffix
            if ext not in _SCANNER_MAP:
                continue
            stem = Path(fname).stem.lower()
            # Only scan likely route files to keep it fast
            if not any(hint in stem for hint in _ROUTE_FILE_HINTS):
                continue
            abs_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(abs_path, repo_root)
            try:
                with open(abs_path, encoding="utf-8", errors="replace") as f:
                    source = f.read()
                eps = _SCANNER_MAP[ext](source, rel_path)
                all_endpoints.extend(eps)
            except Exception as exc:  # pylint: disable=broad-except
                log.debug("endpoint_scanner: skip %s: %s", rel_path, exc)

    result = {
        "endpoints": all_endpoints,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": repo_root,
        "count": len(all_endpoints),
    }

    out_path = endpoints_path()
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        log.info("endpoint_scanner: wrote %d endpoints to %s", len(all_endpoints), out_path)
    except Exception as exc:  # pylint: disable=broad-except
        log.warning("endpoint_scanner: failed to write %s: %s", out_path, exc)

    return result


def load_endpoints(repo_root: str | None = None) -> list[dict]:
    """Load endpoint registry from disk. Returns empty list if not found."""
    from config.paths import endpoints_path  # pylint: disable=import-outside-toplevel
    path = endpoints_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("endpoints", [])
    except Exception:  # pylint: disable=broad-except
        return []
