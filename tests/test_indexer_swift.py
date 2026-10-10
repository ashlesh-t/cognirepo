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

    def test_extension_indexed_as_class(self, fresh_indexer, tmp_path, monkeypatch):
        """Extensions are deliberately CLASS symbols so their methods have a graph parent."""
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        assert _by_name(syms, "Point", 8)["type"] == "CLASS"

    def test_deinit_indexed_with_calls(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "Conn.swift", """\
            class Conn {
                deinit { cleanup() }
            }
        """)
        record = fresh_indexer.index_file("Conn.swift", str(src))
        deinit = next(s for s in record["symbols"] if s["name"] == "deinit")
        assert deinit["type"] == "FUNCTION"
        assert "cleanup" in deinit["calls"]

    def test_vendored_dirs_skipped(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "TokenService.swift", _SWIFT_SRC)
        for d in ("Pods/Alamofire", ".build/checkouts", "Carthage/Checkouts", "DerivedData/x"):
            (tmp_path / d).mkdir(parents=True)
            _write(tmp_path / d, "Vendored.swift", "func vendored() {}\n")
        fresh_indexer.index_repo(str(tmp_path))
        assert list(fresh_indexer.index_data["files"]) == ["TokenService.swift"]

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


_PROPERTY_SRC = """\
    class Shape {
        var area: Int { calc() }
        var name: String {
            get { load() }
            set { store(newValue) }
        }
        var score = 0 {
            willSet { before(newValue) }
            didSet { after() }
        }
        let plain = make()
        func draw() {
            var local: Int { compute() }
        }
    }
    var shared: Shape { build() }
"""


def _callers_of(graph, name: str) -> list[str]:
    """Graph-only who_calls lookup (mirrors tests/test_indexer_multilang.py::_callers_of)."""
    from data.graph.knowledge_graph import EdgeType
    node = f"symbol::{name}"
    if not graph.G.has_node(node):
        candidates = [n for n in graph.G.nodes() if n.endswith(f"::{name}") and not n.startswith("symbol::")]
        if not candidates:
            return []
        node = candidates[0]
    return [s for s in graph.G.successors(node) if graph.G[node][s].get("rel") == EdgeType.CALLS]


class TestSwiftPropertyCalls:
    """#176 — calls in computed properties and property observers are attributed to a
    FUNCTION symbol named after the property, qualified by its type."""

    def _symbols(self, fresh_indexer, tmp_path, monkeypatch) -> list[dict]:
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "Shape.swift", _PROPERTY_SRC)
        return fresh_indexer.index_file("Shape.swift", str(src))["symbols"]

    def test_computed_property(self, fresh_indexer, tmp_path, monkeypatch):
        area = _by_name(self._symbols(fresh_indexer, tmp_path, monkeypatch), "Shape.area", 2)
        assert area["type"] == "FUNCTION"
        assert area["tags"] == ["property"]
        assert area["calls"] == ["calc"]

    def test_getter_setter_pair_is_one_symbol(self, fresh_indexer, tmp_path, monkeypatch):
        syms = self._symbols(fresh_indexer, tmp_path, monkeypatch)
        assert [s["start_line"] for s in syms if s["name"] == "Shape.name"] == [3]
        assert _by_name(syms, "Shape.name", 3)["calls"] == ["load", "store"]

    def test_will_set_and_did_set(self, fresh_indexer, tmp_path, monkeypatch):
        score = _by_name(self._symbols(fresh_indexer, tmp_path, monkeypatch), "Shape.score", 7)
        assert score["type"] == "FUNCTION"
        assert score["calls"] == ["before", "after"]

    def test_top_level_computed_property_is_unqualified(self, fresh_indexer, tmp_path, monkeypatch):
        shared = _by_name(self._symbols(fresh_indexer, tmp_path, monkeypatch), "shared", 16)
        assert shared["calls"] == ["build"]

    def test_stored_and_local_properties_not_symbols(self, fresh_indexer, tmp_path, monkeypatch):
        syms = self._symbols(fresh_indexer, tmp_path, monkeypatch)
        names = {s["name"] for s in syms}
        assert not names & {"plain", "Shape.plain", "local", "draw.local"}
        # the local computed variable's call still belongs to the enclosing function
        assert "compute" in _by_name(syms, "draw", 12)["calls"]

    def test_who_calls_sees_property_callers(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "Shape.swift", _PROPERTY_SRC + "    func calc() -> Int { 1 }\n    func after() {}\n")
        fresh_indexer.index_repo(str(tmp_path))
        assert any(c.endswith("::Shape.area") for c in _callers_of(fresh_indexer.graph, "calc"))
        assert any(c.endswith("::Shape.score") for c in _callers_of(fresh_indexer.graph, "after"))

    def test_multi_binding_declaration_yields_every_property(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "S.swift", """\
            struct S {
                var a: Int { calc() }, b: Int { calc2() }
                var c = 1, d: Int { calc3() }
            }
        """)
        syms = fresh_indexer.index_file("S.swift", str(src))["symbols"]
        props = {s["name"]: s["calls"] for s in syms if s["tags"] == ["property"]}
        assert props == {"S.a": ["calc"], "S.b": ["calc2"], "S.d": ["calc3"]}

    def test_same_property_name_in_two_types_gets_two_graph_nodes(self, fresh_indexer, tmp_path, monkeypatch):
        """SwiftUI: every View has `body`; graph node ids are `file::name`, so the owner prefix
        is what keeps `who_calls` able to say which view made the call."""
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "Views.swift", """\
            struct A: View {
                var body: some View { render() }
            }
            struct B: View {
                var body: some View { draw() }
            }
        """)
        fresh_indexer.index_repo(str(tmp_path))
        assert any(c.endswith("Views.swift::A.body") for c in _callers_of(fresh_indexer.graph, "render"))
        assert any(c.endswith("Views.swift::B.body") for c in _callers_of(fresh_indexer.graph, "draw"))


class TestSharedCallExpressionBranch:
    """The Swift callee fallback lives in the shared `call_expression` branch — pin that
    JS/TS/Go call extraction is unchanged by it."""

    @pytest.mark.parametrize("ext, grammar, code, expected", [
        (".js", "tree_sitter_javascript",
         b"function f() { foo(); obj.bar(); a.b.baz(); }", {"foo", "bar", "baz"}),
        (".ts", "tree_sitter_typescript",
         b"function f(): void { foo(); obj.bar<T>(); }", {"foo", "bar"}),
        (".go", "tree_sitter_go",
         b"package m\nfunc f() { foo(); obj.Bar(); Svc.Run() }", {"foo", "Bar", "Run", "Svc::Run"}),
    ])
    def test_calls_unchanged(self, ext, grammar, code, expected):
        pytest.importorskip(grammar)
        from tree_sitter import Parser
        from intelligence.indexer.ast_indexer import _ts_collect_calls
        from intelligence.indexer.language_registry import _get_language, clear_cache
        clear_cache()
        out: list[str] = []
        _ts_collect_calls(Parser(_get_language(ext)).parse(code).root_node, code, out)
        assert set(out) == expected


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
