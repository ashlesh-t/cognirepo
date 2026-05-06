# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
indexer/inter_repo_indexer.py — Auto-populate OrgGraph from manifest files.

Reads dependency manifests in each repo to build inter-repo IMPORTS edges.
Maps package/module names to sibling repos registered in the org.

Supported manifests:
  Python  — pyproject.toml, requirements.txt, setup.cfg
  Node.js — package.json
  Go      — go.mod
  Rust    — Cargo.toml

Called by:
  - `cognirepo index-repo` (after local index is built, if org is configured)
  - `cognirepo init` (when the user links a new repo to an org/project)
  - `graph/org_graph.py` CLI: `cognirepo link-repos` (manual override)
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__name__)


class DepEdge(NamedTuple):
    src_repo: str   # absolute path
    dst_repo: str   # absolute path
    kind: str       # "IMPORTS" | "CALLS_API" | "SHARES_SCHEMA"
    via: str        # manifest file that triggered this edge


def extract_dependencies(repo_path: str, org_repos: list[str]) -> list[DepEdge]:
    """
    Parse manifest files in `repo_path` and match declared dependencies against
    `org_repos` (absolute paths). Returns a list of DepEdge to add to OrgGraph.

    Matching: package name → repo name (case-insensitive, hyphen/underscore normalized).
    E.g. package "my-auth-service" matches repo at /projects/my_auth_service/.
    """
    abs_repo = os.path.abspath(repo_path)
    root = Path(abs_repo)
    if not root.is_dir():
        return []

    repo_index = _build_repo_index(org_repos, abs_repo)
    declared_deps: set[str] = set()

    declared_deps.update(_parse_pyproject(root))
    declared_deps.update(_parse_requirements(root))
    declared_deps.update(_parse_package_json(root))
    declared_deps.update(_parse_go_mod(root))
    declared_deps.update(_parse_cargo_toml(root))

    edges: list[DepEdge] = []
    for dep_name in declared_deps:
        matched = _match_repo(dep_name, repo_index)
        if matched:
            edges.append(DepEdge(
                src_repo=abs_repo,
                dst_repo=matched,
                kind="IMPORTS",
                via=dep_name,
            ))

    if edges:
        logger.info("inter_repo_indexer: %s → found %d inter-repo deps", abs_repo, len(edges))

    return edges


def build_org_graph_for_org(org_name: str) -> int:
    """
    Build/update OrgGraph for all repos in the given org.
    Returns count of edges added.
    """
    from config.orgs import list_orgs  # pylint: disable=import-outside-toplevel
    from graph.org_graph import get_org_graph, invalidate_org_graph  # pylint: disable=import-outside-toplevel

    orgs = list_orgs()
    org_data = orgs.get(org_name, {})
    all_repos: list[str] = list(org_data.get("repos", []))
    for project_data in org_data.get("projects", {}).values():
        all_repos.extend(project_data.get("repos", []))
    all_repos = [os.path.abspath(r) for r in all_repos if os.path.isdir(r)]

    invalidate_org_graph()
    og = get_org_graph()
    for repo in all_repos:
        og.add_repo(repo, {"name": os.path.basename(repo)})

    total_edges = 0
    for repo in all_repos:
        edges = extract_dependencies(repo, [r for r in all_repos if r != repo])
        for edge in edges:
            og.link(edge.src_repo, edge.dst_repo, kind=edge.kind, auto=True)
            total_edges += 1

    og.save()
    return total_edges


# ── manifest parsers ──────────────────────────────────────────────────────────

def _parse_pyproject(root: Path) -> set[str]:
    path = root / "pyproject.toml"
    if not path.exists():
        return set()
    try:
        try:
            import tomllib  # Python 3.11+  # pylint: disable=import-outside-toplevel
        except ImportError:
            try:
                import tomli as tomllib  # pylint: disable=import-outside-toplevel
            except ImportError:
                return _parse_toml_naive(path.read_text(encoding="utf-8"))
        with open(path, "rb") as f:
            data = tomllib.load(f)
        deps = data.get("project", {}).get("dependencies", [])
        return {_strip_version(d) for d in deps if isinstance(d, str)}
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("_parse_pyproject failed for %s: %s", path, exc)
        return set()


def _parse_requirements(root: Path) -> set[str]:
    names: set[str] = set()
    for fname in ("requirements.txt", "requirements-dev.txt", "requirements/base.txt"):
        path = root / fname
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                names.add(_strip_version(line))
        except OSError:
            pass
    return names


def _parse_package_json(root: Path) -> set[str]:
    path = root / "package.json"
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        names: set[str] = set()
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            names.update(data.get(section, {}).keys())
        return {n.lstrip("@").split("/")[-1] for n in names}
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("_parse_package_json failed: %s", exc)
        return set()


def _parse_go_mod(root: Path) -> set[str]:
    path = root / "go.mod"
    if not path.exists():
        return set()
    names: set[str] = set()
    try:
        in_require = False
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("require ("):
                in_require = True
                continue
            if in_require and line == ")":
                in_require = False
                continue
            if line.startswith("require "):
                parts = line.split()
                if len(parts) > 1:
                    module = parts[1]
                    names.add(module.split("/")[-1])
            elif in_require:
                parts = line.split()
                if parts:
                    module = parts[0]
                    names.add(module.split("/")[-1])
    except OSError:
        pass
    return names


def _parse_cargo_toml(root: Path) -> set[str]:
    path = root / "Cargo.toml"
    if not path.exists():
        return set()
    try:
        try:
            import tomllib  # pylint: disable=import-outside-toplevel
        except ImportError:
            try:
                import tomli as tomllib  # pylint: disable=import-outside-toplevel
            except ImportError:
                return set()
        with open(path, "rb") as f:
            data = tomllib.load(f)
        deps: dict = data.get("dependencies", {})
        deps.update(data.get("dev-dependencies", {}))
        return set(deps.keys())
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("_parse_cargo_toml failed: %s", exc)
        return set()


# ── helpers ───────────────────────────────────────────────────────────────────

def _strip_version(dep: str) -> str:
    """Remove version specifier from a dependency string."""
    return re.split(r"[>=<!@;\[\s]", dep, maxsplit=1)[0].strip()


def _normalize(name: str) -> str:
    """Normalize a package/repo name for comparison (lowercase, _ == -)."""
    return re.sub(r"[-_.]", "", name.lower())


def _build_repo_index(org_repos: list[str], current_repo: str) -> dict[str, str]:
    """Build {normalized_name: abs_path} map for fast lookup."""
    index: dict[str, str] = {}
    for repo in org_repos:
        abs_repo = os.path.abspath(repo)
        if abs_repo == os.path.abspath(current_repo):
            continue
        repo_name = os.path.basename(abs_repo)
        index[_normalize(repo_name)] = abs_repo
    return index


def _match_repo(dep_name: str, repo_index: dict[str, str]) -> str | None:
    """Try to match a dependency name to a known repo path."""
    norm = _normalize(dep_name)
    if norm in repo_index:
        return repo_index[norm]
    # Partial match: dep is a suffix/prefix of a repo name
    for key, path in repo_index.items():
        if norm in key or key in norm:
            return path
    return None


def _parse_toml_naive(text: str) -> set[str]:
    """Very basic TOML parser for dependencies list when tomllib is unavailable."""
    names: set[str] = set()
    in_deps = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped in ('[project.dependencies]', 'dependencies = ['):
            in_deps = True
            continue
        if in_deps:
            if stripped.startswith('[') and not stripped.startswith('"'):
                break
            m = re.search(r'"([^"]+)"', stripped)
            if m:
                names.add(_strip_version(m.group(1)))
    return names
