# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tests/test_dependency_graph.py — unit tests for the dependency_graph tool.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_indexer(files: dict) -> MagicMock:
    """Build a mock ASTIndexer with given files dict."""
    from graph.knowledge_graph import KnowledgeGraph
    from indexer.ast_indexer import ASTIndexer

    ASTIndexer.lookup_symbol.cache_clear()

    # build reverse_index from files
    rev: dict = {}
    for fp, fdata in files.items():
        for sym in fdata.get("symbols", []):
            rev.setdefault(sym["name"], [])
            rev[sym["name"]].append([fp, sym["start_line"]])

    kg = MagicMock(spec=KnowledgeGraph)
    kg.G = MagicMock()
    with patch("indexer.ast_indexer.get_model", return_value=MagicMock()):
        indexer = ASTIndexer(graph=kg)
    indexer.index_data["files"] = files
    indexer.index_data["reverse_index"] = rev
    return indexer


class TestDependencyGraph:
    def _run(self, indexer, module, **kwargs):
        from tools.dependency_graph import dependency_graph
        with patch("tools.dependency_graph._load_indexer", return_value=indexer):
            return dependency_graph(module, **kwargs)

    def test_missing_module_returns_error(self):
        indexer = _make_indexer({})
        result = self._run(indexer, "nonexistent.py")
        assert "error" in result
        assert "not found" in result["error"]

    def test_direct_imports(self):
        files = {
            "auth.py": {"symbols": [
                {"name": "verify_token", "start_line": 1, "calls": ["decode_jwt"]},
            ]},
            "jwt.py": {"symbols": [
                {"name": "decode_jwt", "start_line": 5, "calls": []},
            ]},
        }
        indexer = _make_indexer(files)
        result = self._run(indexer, "auth.py", direction="imports")
        assert "jwt.py" in result["imports"]
        assert result["module"] == "auth.py"

    def test_imported_by(self):
        files = {
            "auth.py": {"symbols": [
                {"name": "login", "start_line": 1, "calls": []},
            ]},
            "api.py": {"symbols": [
                {"name": "handle_request", "start_line": 1, "calls": ["login"]},
            ]},
        }
        indexer = _make_indexer(files)
        result = self._run(indexer, "auth.py", direction="imported_by")
        assert "api.py" in result["imported_by"]

    def test_direction_imports_only(self):
        files = {
            "a.py": {"symbols": [{"name": "f", "start_line": 1, "calls": ["g"]}]},
            "b.py": {"symbols": [{"name": "g", "start_line": 1, "calls": []}]},
        }
        indexer = _make_indexer(files)
        result = self._run(indexer, "a.py", direction="imports")
        assert "imports" in result
        assert "imported_by" in result
        assert result["imported_by"] == []

    def test_direction_imported_by_only(self):
        files = {
            "a.py": {"symbols": [{"name": "f", "start_line": 1, "calls": ["g"]}]},
            "b.py": {"symbols": [{"name": "g", "start_line": 1, "calls": []}]},
        }
        indexer = _make_indexer(files)
        result = self._run(indexer, "b.py", direction="imported_by")
        assert "imported_by" in result
        assert "a.py" in result["imported_by"]
        assert result["imports"] == []

    def test_transitive_depth_1_no_transitive(self):
        files = {
            "a.py": {"symbols": [{"name": "fa", "start_line": 1, "calls": ["fb"]}]},
            "b.py": {"symbols": [{"name": "fb", "start_line": 1, "calls": ["fc"]}]},
            "c.py": {"symbols": [{"name": "fc", "start_line": 1, "calls": []}]},
        }
        indexer = _make_indexer(files)
        result = self._run(indexer, "a.py", direction="imports", depth=1)
        assert result["transitive_imports"] == []

    def test_transitive_depth_2(self):
        files = {
            "a.py": {"symbols": [{"name": "fa", "start_line": 1, "calls": ["fb"]}]},
            "b.py": {"symbols": [{"name": "fb", "start_line": 1, "calls": ["fc"]}]},
            "c.py": {"symbols": [{"name": "fc", "start_line": 1, "calls": []}]},
        }
        indexer = _make_indexer(files)
        result = self._run(indexer, "a.py", direction="imports", depth=3)
        assert "b.py" in result["transitive_imports"] or "c.py" in result["transitive_imports"]

    def test_invalid_direction_returns_error(self):
        indexer = _make_indexer({"a.py": {"symbols": []}})
        result = self._run(indexer, "a.py", direction="invalid")
        assert "error" in result

    def test_partial_name_match(self):
        files = {"src/auth/jwt.py": {"symbols": [{"name": "decode", "start_line": 1, "calls": []}]}}
        indexer = _make_indexer(files)
        result = self._run(indexer, "jwt.py", direction="imports")
        assert result["module"] == "src/auth/jwt.py"

    def test_result_has_depth_field(self):
        files = {"a.py": {"symbols": []}}
        indexer = _make_indexer(files)
        result = self._run(indexer, "a.py", depth=2)
        assert result["depth"] == 2
