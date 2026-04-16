# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
Cross-repository discovery and retrieval logic.

Allows an agent working in Repo A to query findings, symbols, and context
from Repo B if both are members of the same local organization.
"""
import json
import os
import logging
from config.orgs import get_repo_org, list_orgs

logger = logging.getLogger(__name__)

class CrossRepoRouter:
    def __init__(self, current_repo_path: str = "."):
        self.repo_path = os.path.abspath(current_repo_path)
        self.org_name = get_repo_org(self.repo_path)

    def get_sibling_repos(self) -> list[str]:
        """Return absolute paths to all other repos in the same organization."""
        if not self.org_name:
            return []
        
        orgs = list_orgs()
        org_data = orgs.get(self.org_name, {})
        repos = org_data.get("repos", [])
        
        # Return all repos except the current one
        return [r for r in repos if os.path.abspath(r) != self.repo_path]

    def query_org_memories(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Perform semantic search across all repositories in the organization.
        Results are tagged with their source repository.
        """
        siblings = self.get_sibling_repos()
        if not siblings:
            return []

        all_results = []
        from memory.semantic_memory import ProjectSemanticMemory  # pylint: disable=import-outside-toplevel
        from config.paths import set_cognirepo_dir, get_cognirepo_dir  # pylint: disable=import-outside-toplevel

        original_dir = get_cognirepo_dir()

        for repo in siblings:
            cognirepo_dir = os.path.join(repo, ".cognirepo")
            if not os.path.isdir(cognirepo_dir):
                continue
            
            try:
                # Temporarily switch context to sibling repo
                set_cognirepo_dir(cognirepo_dir)
                mem = ProjectSemanticMemory()
                results = mem.search(query, top_k=top_k)
                
                repo_name = os.path.basename(repo)
                for r in results:
                    r["source_repo"] = repo_name
                    r["repo_path"] = repo
                
                all_results.extend(results)
            except Exception as exc:
                logger.error("Failed to query sibling repo %s: %s", repo, exc)
            finally:
                # Always restore original context
                set_cognirepo_dir(original_dir)

        # Re-sort combined results by score (lower is better for L2 distance)
        all_results.sort(key=lambda x: x.get("score", 1.0))
        return all_results[:top_k]
