# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
cli/service_detect.py — Detect sub-repos / microservices in a monorepo root.

Scans immediate subdirectories for project marker files (pom.xml, package.json,
go.mod, etc.) to identify microservice candidates for auto-setup.

IMPORTANT: _SERVICE_MARKERS must stay in sync with
           indexer/language_registry.py::_GRAMMAR_MAP.
           When a new language is added to language_registry, add its build
           file marker here too.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

# ── directories to always skip ────────────────────────────────────────────────

_SKIP_SUBDIRS: frozenset[str] = frozenset({
    # VCS
    ".git", ".svn", ".hg",
    # CogniRepo own data
    ".cognirepo",
    # Build output — never a source service
    "target", "build", "dist", "out", "bin", "obj",
    # Python env
    "venv", ".venv", "env", "__pycache__", ".tox", ".nox", ".eggs",
    # Node
    "node_modules", ".next", ".nuxt", ".turbo", ".parcel-cache",
    # IDE
    ".idea", ".vscode",
    # Static assets — not a service
    "public", "static", "assets",
    # Gradle cache
    ".gradle",
})

# ── project marker → (default_service_type, lang_hint) ───────────────────────
# Keep in sync with indexer/language_registry.py::_GRAMMAR_MAP

_SERVICE_MARKERS: dict[str, tuple[str | None, str]] = {
    # Java / JVM
    "pom.xml":              ("rest_api", "Java/Maven"),
    "build.gradle":         ("rest_api", "Java/Gradle"),
    "build.gradle.kts":     ("rest_api", "Kotlin/Gradle"),
    # Go
    "go.mod":               ("rest_api", "Go"),
    # Rust
    "Cargo.toml":           ("worker",   "Rust"),
    # Python
    "pyproject.toml":       ("worker",   "Python"),
    "setup.py":             ("worker",   "Python"),
    "requirements.txt":     ("worker",   "Python"),
    # Node.js — type refined by _infer_node_type()
    "package.json":         (None,       "Node.js"),
    # Ruby
    "Gemfile":              ("rest_api", "Ruby"),
    # PHP
    "composer.json":        ("rest_api", "PHP"),
    # C# / .NET
    "*.csproj":             ("rest_api", "C#/.NET"),
    # Dart / Flutter
    "pubspec.yaml":         ("frontend", "Dart/Flutter"),
}

# ── Node.js dep signals for service-type inference ────────────────────────────

_FRONTEND_DEPS = frozenset({
    "react", "vue", "angular", "@angular/core", "svelte", "solid-js",
    "vite", "next", "nuxt", "@svelte-kit/core", "astro", "gatsby",
})
_REST_DEPS = frozenset({
    "express", "fastify", "koa", "hapi", "@hapi/hapi",
    "nest", "@nestjs/core", "restify", "polka", "micro",
})


# ── dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class ServiceCandidate:
    name: str            # subdir basename
    path: str            # absolute path
    service_type: str    # rest_api | frontend | worker | library | other
    lang_hint: str       # "Java/Maven", "Node.js", etc. — shown in table
    already_init: bool   # True if .cognirepo/ already exists
    markers: list[str] = field(default_factory=list)


# ── helpers ───────────────────────────────────────────────────────────────────

def _infer_node_type(subdir: str) -> str:
    """Peek inside package.json to distinguish frontend / rest_api / worker."""
    pkg = os.path.join(subdir, "package.json")
    try:
        with open(pkg, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return "worker"

    all_deps: set[str] = set()
    all_deps.update(data.get("dependencies", {}).keys())
    all_deps.update(data.get("devDependencies", {}).keys())

    if all_deps & _FRONTEND_DEPS:
        return "frontend"
    if all_deps & _REST_DEPS:
        return "rest_api"

    # Peek scripts for common web server hints
    scripts = data.get("scripts", {})
    script_vals = " ".join(scripts.values()).lower()
    if any(w in script_vals for w in ("react-scripts", "vite", "webpack", "next build")):
        return "frontend"
    if any(w in script_vals for w in ("express", "fastify", "node server", "node app")):
        return "rest_api"

    return "worker"


def _matches_glob_marker(subdir: str, marker: str) -> bool:
    """Handle simple wildcard markers like '*.csproj'."""
    if "*" not in marker:
        return os.path.exists(os.path.join(subdir, marker))
    # Simple glob: only supports leading '*'
    ext = marker.lstrip("*")
    try:
        return any(f.endswith(ext) for f in os.listdir(subdir))
    except OSError:
        return False


# ── public API ────────────────────────────────────────────────────────────────

def detect_sub_repos(root: str) -> list[ServiceCandidate]:
    """
    Scan immediate subdirectories of `root` for microservice candidates.

    Returns sorted list: already-initialised services first, then alphabetical.
    """
    candidates: list[ServiceCandidate] = []
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return []

    for entry in entries:
        if entry in _SKIP_SUBDIRS or entry.startswith("."):
            continue
        subdir = os.path.join(root, entry)
        if not os.path.isdir(subdir):
            continue

        found_markers: list[str] = []
        service_type: str | None = None
        lang_hint = ""

        for marker, (stype, hint) in _SERVICE_MARKERS.items():
            if _matches_glob_marker(subdir, marker):
                found_markers.append(marker)
                if service_type is None:
                    service_type = stype
                    lang_hint = hint

        if not found_markers:
            continue

        # Refine Node.js type
        if "package.json" in found_markers and service_type is None:
            service_type = _infer_node_type(subdir)

        if service_type is None:
            service_type = "other"

        already_init = os.path.isdir(os.path.join(subdir, ".cognirepo"))

        candidates.append(ServiceCandidate(
            name=entry,
            path=os.path.abspath(subdir),
            service_type=service_type,
            lang_hint=lang_hint,
            already_init=already_init,
            markers=found_markers,
        ))

    # already-init first, then alphabetical
    candidates.sort(key=lambda c: (not c.already_init, c.name.lower()))
    return candidates
