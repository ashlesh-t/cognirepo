# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
Cross-repository discovery and retrieval logic.

Allows an agent working in Repo A to query findings, symbols, and context
from Repo B if both are members of the same local organization.
"""
import json
import os
import logging
from config.orgs import get_repo_org, get_repo_project, get_project_repos, list_orgs, purge_stale_repos
from config.paths import get_cognirepo_dir_for_repo

logger = logging.getLogger(__name__)

class CrossRepoRouter:
    def __init__(self, current_repo_path: str = "."):
        self.repo_path = os.path.abspath(current_repo_path)
        self.org_name = get_repo_org(self.repo_path)
        _proj = get_repo_project(self.repo_path)
        self._project_org, self._project_name = _proj if _proj else (None, None)

    def get_sibling_repos(self) -> list[str]:
        """
        Return absolute paths to all sibling repos (same parent in org graph).
        Falls back to orgs.json for backward compatibility if no graph siblings found.
        """
        try:
            from graph.org_graph import get_org_graph  # pylint: disable=import-outside-toplevel
            og = get_org_graph()
            siblings = og.get_siblings(self.repo_path)
            if siblings:
                return [s for s in siblings if os.path.isdir(s)]
            # Also include repos where self is a child (all siblings of self's parent)
            children = og.get_children(self.repo_path)
            if children:
                return [c for c in children if os.path.isdir(c)]
        except Exception:  # pylint: disable=broad-except
            pass
        # Fallback: orgs.json (backward compat)
        if not self.org_name:
            return []
        purge_stale_repos(self.org_name)
        orgs = list_orgs()
        org_data = orgs.get(self.org_name, {})
        repos = org_data.get("repos", [])
        return [r for r in repos if os.path.abspath(r) != self.repo_path]

    def get_all_org_repos(self) -> list[str]:
        """Return absolute paths to ALL repos across every project in the org.

        Reads from OrgGraph (authoritative) first, then merges in any repos
        from the legacy orgs.json file for backward compatibility.
        """
        seen: set[str] = set()
        result: list[str] = []

        # Primary source: OrgGraph (~/.cognirepo/org_graph.pkl) — this is where
        # child repos registered via `cognirepo init --parent-repo` live.
        try:
            from graph.org_graph import get_org_graph  # pylint: disable=import-outside-toplevel
            og = get_org_graph()
            for repo_path in og.list_repos():
                abs_repo = os.path.realpath(os.path.normpath(repo_path))
                if abs_repo != self.repo_path and abs_repo not in seen and os.path.isdir(abs_repo):
                    seen.add(abs_repo)
                    result.append(abs_repo)
        except Exception:  # pylint: disable=broad-except
            pass

        # Secondary source: orgs.json (legacy, kept for backward compatibility)
        if not self.org_name:
            return result
        try:
            purge_stale_repos(self.org_name)
            orgs = list_orgs()
            org_data = orgs.get(self.org_name, {})
            for repo in org_data.get("repos", []):
                abs_repo = os.path.realpath(os.path.normpath(repo))
                if abs_repo != self.repo_path and abs_repo not in seen:
                    seen.add(abs_repo)
                    result.append(abs_repo)
            for project_data in org_data.get("projects", {}).values():
                for repo in project_data.get("repos", []):
                    abs_repo = os.path.realpath(os.path.normpath(repo))
                    if abs_repo != self.repo_path and abs_repo not in seen:
                        seen.add(abs_repo)
                        result.append(abs_repo)
        except Exception:  # pylint: disable=broad-except
            pass
        return result

    def query_all_org_repos(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Semantic search across ALL repos in the org (top-level + all projects).
        Wider than query_org_memories which only covers top-level org repos.
        """
        all_repos = self.get_all_org_repos()
        if not all_repos:
            return []
        all_results: list[dict] = []
        seen_hashes: set[int] = set()
        from config.paths import _CTX_DIR  # pylint: disable=import-outside-toplevel
        for repo in all_repos:
            repo_norm = os.path.realpath(os.path.normpath(repo))
            cognirepo_dir = get_cognirepo_dir_for_repo(repo_norm)
            index_exists = os.path.isdir(cognirepo_dir)
            logger.debug(
                "org_search: querying repo=%s, cognirepo_dir=%s, index_exists=%s",
                repo_norm, cognirepo_dir, index_exists,
            )
            if not index_exists:
                logger.warning(
                    "org_search: skipping repo '%s' — .cognirepo/ index not found at %s",
                    os.path.basename(repo_norm), cognirepo_dir,
                )
                continue
            token = _CTX_DIR.set(cognirepo_dir)
            try:
                # Use hybrid retrieval (AST symbols + semantic memories) so code-level
                # results are included — SemanticMemory alone only returns user-stored
                # memories and misses all indexed code symbols.
                from retrieval.hybrid import hybrid_retrieve  # pylint: disable=import-outside-toplevel
                results = hybrid_retrieve(query, top_k=top_k)
                repo_name = os.path.basename(repo_norm)
                for r in results:
                    r["source_repo"] = repo_name
                    r["repo_path"] = repo_norm
                    # Deduplicate by text content across all repos
                    text_hash = hash(r.get("text", ""))
                    if text_hash not in seen_hashes:
                        seen_hashes.add(text_hash)
                        all_results.append(r)
            except Exception as exc:
                logger.error("Failed to query repo %s: %s", repo_norm, exc)
            finally:
                _CTX_DIR.reset(token)
        # Sort descending by score (highest relevance first)
        all_results.sort(key=lambda x: x.get("final_score", x.get("score", 0.0)), reverse=True)
        return all_results[:top_k]

    def query_org_memories(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Perform semantic search across all repositories in the organization.
        Results are tagged with their source repository.
        """
        siblings = self.get_sibling_repos()
        if not siblings:
            return []

        all_results = []
        from memory.semantic_memory import SemanticMemory  # pylint: disable=import-outside-toplevel
        from config.paths import _CTX_DIR  # pylint: disable=import-outside-toplevel

        for repo in siblings:
            cognirepo_dir = get_cognirepo_dir_for_repo(repo)
            if not os.path.isdir(cognirepo_dir):
                continue

            # Use ContextVar for thread-safe per-task directory switching.
            # This avoids mutating the process-wide _OVERRIDE_DIR global
            # which would race under concurrent MCP calls.
            token = _CTX_DIR.set(cognirepo_dir)
            try:
                mem = SemanticMemory()
                results = mem.search(query, top_k=top_k)

                repo_name = os.path.basename(repo)
                for r in results:
                    r["source_repo"] = repo_name
                    r["repo_path"] = repo

                all_results.extend(results)
            except Exception as exc:
                logger.error("Failed to query sibling repo %s: %s", repo, exc)
            finally:
                _CTX_DIR.reset(token)

        # Re-sort combined results by score (higher is better)
        all_results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        return all_results[:top_k]

    def query_project_memories(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Search shared ProjectMemory for the project this repo belongs to.
        Narrower than query_org_memories — only the current project scope.
        """
        if not self._project_org or not self._project_name:
            return []
        try:
            from memory.project_memory import ProjectMemory  # pylint: disable=import-outside-toplevel
            pm = ProjectMemory(self._project_org, self._project_name)
            results = pm.search(query, top_k=top_k)
            for r in results:
                r.setdefault("scope", "project")
                r.setdefault("project", self._project_name)
                r.setdefault("org", self._project_org)
            return results
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("query_project_memories failed: %s", exc)
            return []

    def get_context_summary(self) -> dict:
        """Return org/project/sibling context for the current repo."""
        proj_repos = (
            get_project_repos(self._project_org, self._project_name)
            if self._project_org and self._project_name
            else []
        )
        return {
            "org": self.org_name,
            "project": self._project_name,
            "project_org": self._project_org,
            "sibling_repos": self.get_sibling_repos(),
            "project_repos": [r for r in proj_repos if os.path.abspath(r) != self.repo_path],
        }
