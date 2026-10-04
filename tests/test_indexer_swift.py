# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_indexer_swift.py — Swift (.swift) indexing via tree-sitter-swift (#75).

Covers:
  - classes, structs, enums, actors, protocols (and extensions)
  - functions, init and protocol requirements
  - call extraction for foo() and obj.foo()
  - inheritance list extraction
  - registry / Package.swift service-marker wiring
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("tree_sitter_swift")


@pytest.fixture()
def fresh_indexer(isolated_cognirepo):
    import numpy as np
    fake_model = MagicMock()
    fake_model.embed.side_effect = lambda texts: iter([np.zeros(384, dtype="float32") for _ in texts])
    with patch("intelligence.indexer.ast_indexer.get_model", return_value=fake_model):
        from data.graph.knowledge_graph import KnowledgeGraph
        from intelligence.indexer.ast_indexer import ASTIndexer
        from intelligence.indexer.language_registry import clear_cache
        clear_cache()
        kg = KnowledgeGraph()
        return ASTIndexer(graph=kg)


def _write(tmp: Path, name: str, content: str) -> Path:
    p = tmp / name
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


_SWIFT_SRC = """\
    import Foundation

    protocol Verifier { func verify(_ token: String) -> Bool }
    struct Point { var x: Int }
    enum Status { case active }
    actor Cache {}

    extension Point {
        func norm() -> Int { return abs(x) }
    }

    class TokenService: BaseService, Verifier {
        init() { setup() }

        func verify(_ token: String) -> Bool {
            helper.check(token)
            decode(token)
            return Helper.isValid(token)
        }
    }

    func makeService() -> TokenService { return TokenService() }
"""


def _symbols(fresh_indexer, tmp_path, monkeypatch) -> list[dict]:
    monkeypatch.chdir(tmp_path)
    src = _write(tmp_path, "TokenService.swift", _SWIFT_SRC)
    record = fresh_indexer.index_file("TokenService.swift", str(src))
    return record["symbols"]


def _by_name(symbols: list[dict], name: str, line: int) -> dict:
    return next(s for s in symbols if s["name"] == name and s["start_line"] == line)


class TestSwiftIndexing:
    def test_type_declarations_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        classes = {s["name"] for s in syms if s["type"] == "CLASS"}
        assert {"Verifier", "Point", "Status", "Cache", "TokenService"} <= classes

    def test_extension_recorded_at_its_own_line(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        point_lines = sorted(s["start_line"] for s in syms if s["name"] == "Point")
        assert point_lines == [4, 8]

    def test_functions_init_and_requirements_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        functions = {(s["name"], s["start_line"]) for s in syms if s["type"] == "FUNCTION"}
        assert {("verify", 3), ("norm", 9), ("init", 13), ("verify", 15), ("makeService", 22)} <= functions

    def test_calls_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        assert {"check", "decode", "isValid"} <= set(_by_name(syms, "verify", 15)["calls"])
        assert "setup" in _by_name(syms, "init", 13)["calls"]
        assert "abs" in _by_name(syms, "norm", 9)["calls"]

    def test_inheritance_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        assert _by_name(syms, "TokenService", 12)["bases"] == ["BaseService", "Verifier"]

    def test_index_repo_reports_swift(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "TokenService.swift", _SWIFT_SRC)
        summary = fresh_indexer.index_repo(str(tmp_path))
        assert summary["symbols"] > 0
        assert "Swift" in summary["languages"]


class TestSwiftRegistry:
    def test_grammar_mapped(self):
        from intelligence.indexer.language_registry import _GRAMMAR_MAP, lang_label, lang_name
        assert _GRAMMAR_MAP[".swift"] == "tree_sitter_swift"
        assert lang_label(".swift") == "Swift"
        assert lang_name(".swift") == "swift"

    def test_swift_supported(self):
        from intelligence.indexer.language_registry import is_supported, clear_cache
        clear_cache()
        assert is_supported(Path("main.swift")) is True

    def test_package_swift_service_marker(self, tmp_path):
        from interface.cli.service_detect import _SERVICE_MARKERS, detect_sub_repos
        assert _SERVICE_MARKERS["Package.swift"] == ("worker", "Swift/SwiftPM")
        svc = tmp_path / "ios-sdk"
        svc.mkdir()
        (svc / "Package.swift").write_text("// swift-tools-version:5.9\n")
        found = detect_sub_repos(str(tmp_path))
        assert [c.name for c in found] == ["ios-sdk"]

    def test_semantic_search_language_filter(self):
        from interface.tools.semantic_search_code import _lang_extensions
        assert _lang_extensions("swift") == {".swift"}
