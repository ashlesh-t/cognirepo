# pylint: disable=missing-docstring, import-outside-toplevel, too-few-public-methods
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_cross_repo.py — Cross-repo and org-wide tool unit tests.

Covers: CrossRepoRouter, org_wide_search, cross_repo_search, list_org_context,
org_dependencies, link_repos, cross_repo_traverse, and empty-org graceful handling.
"""
from __future__ import annotations

import os

import pytest
from core.config.orgs import create_org, link_repo_to_org
from retrieval.cross_repo import CrossRepoRouter
from core.config.paths import set_cognirepo_dir


# ── CrossRepoRouter basics ────────────────────────────────────────────────────

def test_get_sibling_repos(isolated_cognirepo, tmp_path):
    repo_a = str(tmp_path / "repo_a")
    repo_b = str(tmp_path / "repo_b")
    os.makedirs(repo_a)
    os.makedirs(repo_b)

    create_org("my-org")
    link_repo_to_org(repo_a, "my-org")
    link_repo_to_org(repo_b, "my-org")

    router = CrossRepoRouter(current_repo_path=repo_a)
    siblings = router.get_sibling_repos()

    assert len(siblings) == 1
    assert os.path.abspath(repo_b) in siblings


def test_query_org_memories_empty(isolated_cognirepo, tmp_path):
    repo_a = str(tmp_path / "repo_a")
    os.makedirs(repo_a)

    router = CrossRepoRouter(current_repo_path=repo_a)
    assert router.query_org_memories("test") == []


# ── MCP tool: cross_repo_search ───────────────────────────────────────────────

class TestCrossRepoSearch:
    def test_scope_project_returns_dict(self, isolated_cognirepo):
        from server.mcp_server import cross_repo_search
        result = cross_repo_search("authentication", scope="project")
        assert isinstance(result, dict)
        assert "scope" in result
        assert result["scope"] == "project"
        assert "results" in result
        assert isinstance(result["results"], list)

    def test_scope_org_returns_dict(self, isolated_cognirepo):
        from server.mcp_server import cross_repo_search
        result = cross_repo_search("middleware", scope="org")
        assert isinstance(result, dict)
        assert result["scope"] == "org"
        assert "results" in result

    def test_has_sibling_count_key(self, isolated_cognirepo):
        from server.mcp_server import cross_repo_search
        result = cross_repo_search("auth")
        assert "sibling_count" in result
        assert isinstance(result["sibling_count"], int)

    def test_empty_repo_returns_empty_results(self, isolated_cognirepo):
        from server.mcp_server import cross_repo_search
        result = cross_repo_search("anything_xyz_not_found")
        assert result["results"] == []


# ── MCP tool: org_wide_search ─────────────────────────────────────────────────

class TestOrgWideSearch:
    def test_returns_dict_with_meta(self, isolated_cognirepo):
        from server.mcp_server import org_wide_search
        result = org_wide_search("authentication")
        assert isinstance(result, dict)
        assert isinstance(result["results"], list)
        assert "repos_searched" in result
        assert "repos_skipped" in result
        assert result["count"] == len(result["results"])

    def test_empty_org_returns_empty_results(self, isolated_cognirepo, monkeypatch):
        # The global ~/.cognirepo/org_graph.pkl leaks into tests; force an
        # actually-empty org so the empty-path contract is what's tested.
        from retrieval.cross_repo import CrossRepoRouter
        monkeypatch.setattr(CrossRepoRouter, "get_all_org_repos", lambda self: [])
        from server.mcp_server import org_wide_search
        result = org_wide_search("something_nonexistent_zzz")
        assert result["results"] == []
        assert result["count"] == 0
        assert result["repos_searched"] == []

    def test_top_k_respected(self, isolated_cognirepo):
        from server.mcp_server import org_wide_search
        result = org_wide_search("auth", top_k=3)
        assert len(result["results"]) <= 3


# ── MCP tool: list_org_context ────────────────────────────────────────────────

class TestListOrgContext:
    def test_returns_dict(self, isolated_cognirepo):
        from server.mcp_server import list_org_context
        result = list_org_context()
        assert isinstance(result, dict)

    def test_has_sibling_repos_key(self, isolated_cognirepo):
        from server.mcp_server import list_org_context
        result = list_org_context()
        assert "sibling_repos" in result
        assert isinstance(result["sibling_repos"], list)

    def test_empty_org_returns_gracefully(self, isolated_cognirepo):
        from server.mcp_server import list_org_context
        result = list_org_context()
        assert result["sibling_repos"] == []


# ── MCP tool: org_dependencies ────────────────────────────────────────────────

class TestOrgDependencies:
    def test_returns_required_keys(self, isolated_cognirepo):
        from server.mcp_server import org_dependencies
        result = org_dependencies()
        required = [
            "current_repo", "current_repo_name", "organization",
            "direct_dependencies", "transitive_dependencies",
            "direct_dependents", "transitive_dependents",
        ]
        for key in required:
            assert key in result, f"Missing key: {key}"

    def test_lists_are_lists(self, isolated_cognirepo):
        from server.mcp_server import org_dependencies
        result = org_dependencies()
        assert isinstance(result["direct_dependencies"], list)
        assert isinstance(result["direct_dependents"], list)
        assert isinstance(result["transitive_dependencies"], list)
        assert isinstance(result["transitive_dependents"], list)

    def test_empty_org_has_empty_dep_lists(self, isolated_cognirepo):
        from server.mcp_server import org_dependencies
        result = org_dependencies()
        assert result["direct_dependencies"] == []
        assert result["direct_dependents"] == []


# ── MCP tool: link_repos ─────────────────────────────────────────────────────

class TestLinkRepos:
    def test_link_repos_basic(self, isolated_cognirepo, tmp_path):
        from server.mcp_server import link_repos
        src = str(tmp_path / "service_a")
        dst = str(tmp_path / "service_b")
        result = link_repos(src_repo=src, dst_repo=dst, relationship="imports")
        assert result["linked"] is True
        assert result["edge"]["kind"] == "IMPORTS"
        assert result["edge"]["src"] == src
        assert result["edge"]["dst"] == dst

    def test_link_repos_calls_api(self, isolated_cognirepo, tmp_path):
        from server.mcp_server import link_repos
        src = str(tmp_path / "api_gateway")
        dst = str(tmp_path / "auth_service")
        result = link_repos(src_repo=src, dst_repo=dst, relationship="calls_api")
        assert result["linked"] is True
        assert result["edge"]["kind"] == "CALLS_API"

    def test_link_repos_relationship_mapping(self, isolated_cognirepo, tmp_path):
        from server.mcp_server import link_repos
        mappings = [
            ("imports", "IMPORTS"),
            ("calls_api", "CALLS_API"),
            ("shares_schema", "SHARES_SCHEMA"),
            ("discovered", "DISCOVERED"),
            ("child_of", "CHILD_OF"),
        ]
        for idx, (rel, kind) in enumerate(mappings):
            result = link_repos(
                src_repo=str(tmp_path / f"a{idx}"),
                dst_repo=str(tmp_path / f"b{idx}"),
                relationship=rel,
            )
            assert result["edge"]["kind"] == kind, f"Expected {kind}, got {result['edge']['kind']}"

    def test_link_repos_unknown_relationship_defaults_to_discovered(self, isolated_cognirepo, tmp_path):
        from server.mcp_server import link_repos
        result = link_repos(
            src_repo=str(tmp_path / "x"),
            dst_repo=str(tmp_path / "y"),
            relationship="unknown_kind",
        )
        assert result["edge"]["kind"] == "DISCOVERED"

    def test_link_repos_returns_linked_true(self, isolated_cognirepo, tmp_path):
        from server.mcp_server import link_repos
        result = link_repos(
            src_repo=str(tmp_path / "p"),
            dst_repo=str(tmp_path / "q"),
        )
        assert result["linked"] is True


# ── MCP tool: cross_repo_traverse ────────────────────────────────────────────

class TestCrossRepoTraverse:
    def test_direction_both_returns_both_keys(self, isolated_cognirepo):
        from server.mcp_server import cross_repo_traverse
        result = cross_repo_traverse(direction="both")
        assert isinstance(result, dict)
        assert "dependencies" in result
        assert "dependents" in result

    def test_direction_dependencies_only(self, isolated_cognirepo):
        from server.mcp_server import cross_repo_traverse
        result = cross_repo_traverse(direction="dependencies")
        assert "dependencies" in result
        assert "dependents" not in result

    def test_direction_dependents_only(self, isolated_cognirepo):
        from server.mcp_server import cross_repo_traverse
        result = cross_repo_traverse(direction="dependents")
        assert "dependents" in result
        assert "dependencies" not in result

    def test_has_start_repo_key(self, isolated_cognirepo):
        from server.mcp_server import cross_repo_traverse
        result = cross_repo_traverse()
        assert "start_repo" in result
        assert "start_repo_name" in result

    def test_empty_org_returns_empty_deps(self, isolated_cognirepo):
        from server.mcp_server import cross_repo_traverse
        result = cross_repo_traverse(direction="both")
        assert result["dependencies"] == []
        assert result["dependents"] == []

    def test_link_repos_then_traverse(self, isolated_cognirepo, tmp_path):
        """End-to-end: link two repos then traverse finds the edge."""
        from server.mcp_server import link_repos, cross_repo_traverse
        src = str(tmp_path)
        dst = str(tmp_path / "child_service")
        link_repos(src_repo=src, dst_repo=dst, relationship="imports")
        result = cross_repo_traverse(start_repo=src, direction="dependencies")
        assert isinstance(result["dependencies"], list)
        # The traversal should now see at least 1 dependency
        assert len(result["dependencies"]) >= 1
