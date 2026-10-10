# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_indexer_csharp.py — C# (.cs) indexing via tree-sitter-c-sharp (#74).

Covers:
  - classes, interfaces, structs, records, enums
  - methods and local functions; constructors, finalizers and properties with accessor
    bodies (#177)
  - call extraction for Foo(), obj.Foo() and generic Foo<T>() invocations
  - base list extraction
  - registry / service-marker wiring
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("tree_sitter_c_sharp")


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


_CS_SRC = """\
    namespace App.Auth {
        public interface IVerifier { bool Verify(string token); }
        public record UserDto(string Name);
        public struct Point { public int X; }
        public enum Status { Active }

        public class TokenService : BaseService, IVerifier {
            public TokenService() { Init(); }

            public bool Verify(string token) {
                var ok = helper.Check(token);
                Decode(token);
                cache?.Foo(token);
                helper.Inner?.Baz();
                return Helper.IsValid<string>(token);
            }

            int Total() {
                int Add(int a) => a + 1;
                return Add(1);
            }
        }

        public record struct Pair(int A, int B);
    }
"""


def _symbols(fresh_indexer, tmp_path, monkeypatch) -> list[dict]:
    monkeypatch.chdir(tmp_path)
    src = _write(tmp_path, "TokenService.cs", _CS_SRC)
    record = fresh_indexer.index_file("TokenService.cs", str(src))
    return record["symbols"]


def _by_name(symbols: list[dict], name: str, kind: str) -> dict:
    return next(s for s in symbols if s["name"] == name and s["type"] == kind)


class TestCSharpIndexing:
    def test_type_declarations_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        classes = {s["name"] for s in syms if s["type"] == "CLASS"}
        assert {"IVerifier", "UserDto", "Point", "Status", "TokenService", "Pair"} <= classes

    def test_methods_and_local_functions_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        functions = {s["name"] for s in syms if s["type"] == "FUNCTION"}
        assert {"Verify", "Total", "Add"} <= functions

    def test_constructor_not_named_after_class(self, fresh_indexer, tmp_path, monkeypatch):
        """A FUNCTION named like the class would share its `file::TokenService` node id."""
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        assert not any(s["name"] == "TokenService" and s["type"] == "FUNCTION" for s in syms)
        assert "Init" in _by_name(syms, "TokenService.constructor", "FUNCTION")["calls"]

    def test_calls_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        verify = next(s for s in syms if s["name"] == "Verify" and s["start_line"] == 10)
        assert {"Check", "Decode", "IsValid"} <= set(verify["calls"])
        # null-conditional calls: `a?.Foo()` / `b.Bar?.Baz()`
        assert {"Foo", "Baz"} <= set(verify["calls"])
        assert "Add" in _by_name(syms, "Total", "FUNCTION")["calls"]

    def test_base_list_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        assert _by_name(syms, "TokenService", "CLASS")["bases"] == ["BaseService", "IVerifier"]

    def test_msbuild_obj_dir_skipped(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "TokenService.cs", _CS_SRC)
        (tmp_path / "obj" / "Debug").mkdir(parents=True)
        _write(tmp_path / "obj" / "Debug", "App.AssemblyInfo.cs", "class GeneratedInfo { }\n")
        fresh_indexer.index_repo(str(tmp_path))
        assert not any("obj" in Path(f).parts for f in fresh_indexer.index_data["files"])

    def test_index_repo_reports_csharp(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "TokenService.cs", _CS_SRC)
        summary = fresh_indexer.index_repo(str(tmp_path))
        assert summary["symbols"] > 0
        assert "C#" in summary["languages"]


_MEMBERS_SRC = """\
    public class Svc : Base {
        public Svc(IRepo repo) : base(repo) { Wire(repo); }
        static Svc() { Boot(); }
        ~Svc() { Release(); }
        public int Count {
            get { return Load(); }
            set { Store(value); }
        }
        public int Area => Calc();
        public int Bodied { get => Fetch(); init => Assign(value); }
        public int Auto { get; set; } = Make();
        public void Run() { }
    }
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


class TestCSharpMemberCalls:
    """#177 — calls in constructors, property accessors and finalizers are attributed."""

    def _symbols(self, fresh_indexer, tmp_path, monkeypatch) -> list[dict]:
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "Svc.cs", _MEMBERS_SRC)
        return fresh_indexer.index_file("Svc.cs", str(src))["symbols"]

    def test_constructors(self, fresh_indexer, tmp_path, monkeypatch):
        syms = self._symbols(fresh_indexer, tmp_path, monkeypatch)
        ctors = {s["start_line"]: s["calls"] for s in syms if s["name"] == "Svc.constructor"}
        assert ctors == {2: ["Wire"], 3: ["Boot"]}  # instance and static constructor

    def test_finalizer(self, fresh_indexer, tmp_path, monkeypatch):
        fin = _by_name(self._symbols(fresh_indexer, tmp_path, monkeypatch), "~Svc", "FUNCTION")
        assert fin["calls"] == ["Release"]

    def test_property_accessors(self, fresh_indexer, tmp_path, monkeypatch):
        syms = self._symbols(fresh_indexer, tmp_path, monkeypatch)
        count = _by_name(syms, "Svc.Count", "FUNCTION")
        assert count["tags"] == ["property"]
        assert count["calls"] == ["Load", "Store"]
        assert _by_name(syms, "Svc.Area", "FUNCTION")["calls"] == ["Calc"]  # expression-bodied
        assert _by_name(syms, "Svc.Bodied", "FUNCTION")["calls"] == ["Fetch", "Assign"]

    def test_auto_property_not_a_symbol(self, fresh_indexer, tmp_path, monkeypatch):
        syms = self._symbols(fresh_indexer, tmp_path, monkeypatch)
        assert not {"Auto", "Svc.Auto"} & {s["name"] for s in syms}

    def test_who_calls_sees_member_callers(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "Svc.cs", _MEMBERS_SRC)
        _write(tmp_path, "Helpers.cs", """\
            static class Helpers {
                static void Wire(IRepo r) { }
                static int Calc() => 1;
                static void Release() { }
            }
        """)
        fresh_indexer.index_repo(str(tmp_path))
        graph = fresh_indexer.graph
        assert any(c.endswith("::Svc.constructor") for c in _callers_of(graph, "Wire"))
        assert any(c.endswith("::Svc.Area") for c in _callers_of(graph, "Calc"))
        assert any(c.endswith("::~Svc") for c in _callers_of(graph, "Release"))

    def test_property_named_like_its_type_keeps_the_class_node(self, fresh_indexer, tmp_path, monkeypatch):
        """The "Color Color" pattern: a property named like a class in the same file must not
        overwrite that CLASS's `file::name` graph node or hang its calls on it."""
        from data.graph.knowledge_graph import EdgeType
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "Model.cs", """\
            class Base { }
            class Customer : Base { public int Id { get; set; } }
            class Order { public Customer Customer { get { return repo.Load(); } } }
        """)
        fresh_indexer.index_repo(str(tmp_path))
        g = fresh_indexer.graph.G
        cls = "Model.cs::Customer"
        assert g.nodes[cls]["line"] == 2
        assert not [n for n in g.successors(cls) if g[cls][n].get("rel") == EdgeType.CALLS]
        assert any(c.endswith("::Order.Customer") for c in _callers_of(fresh_indexer.graph, "Load"))

    def test_constructors_of_two_classes_get_distinct_graph_nodes(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "Two.cs", """\
            class Order { public Order() { Wire(); } }
            class Invoice { public Invoice() { Wire(); } }
            static class Di { static void Wire() { } }
        """)
        fresh_indexer.index_repo(str(tmp_path))
        callers = set(_callers_of(fresh_indexer.graph, "Wire"))
        assert {"Two.cs::Order.constructor", "Two.cs::Invoice.constructor"} <= callers


class TestJavaRecordsAreClasses:
    def test_java_record_indexed_as_class(self, fresh_indexer, tmp_path, monkeypatch):
        """`record_declaration` is shared with Java 16+ records — pin that intentionally."""
        pytest.importorskip("tree_sitter_java")
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "Point.java", "record Point(int x, int y) {}\n")
        record = fresh_indexer.index_file("Point.java", str(src))
        assert ("CLASS", "Point") in {(s["type"], s["name"]) for s in record["symbols"]}


class TestCSharpRegistry:
    def test_grammar_mapped(self):
        from intelligence.indexer.language_registry import _GRAMMAR_MAP, lang_label, lang_name
        assert _GRAMMAR_MAP[".cs"] == "tree_sitter_c_sharp"
        assert lang_label(".cs") == "C#"
        assert lang_name(".cs") == "csharp"

    def test_cs_supported(self):
        from intelligence.indexer.language_registry import is_supported, clear_cache
        clear_cache()
        assert is_supported(Path("Program.cs")) is True

    def test_csproj_service_marker(self):
        from interface.cli.service_detect import _SERVICE_MARKERS
        assert _SERVICE_MARKERS["*.csproj"][1] == "C#/.NET"

    def test_semantic_search_language_filter(self):
        from interface.tools.semantic_search_code import _lang_extensions
        assert _lang_extensions("csharp") == {".cs"}
