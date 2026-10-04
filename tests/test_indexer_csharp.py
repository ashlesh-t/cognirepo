# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_indexer_csharp.py — C# (.cs) indexing via tree-sitter-c-sharp (#74).

Covers:
  - classes, interfaces, structs, records, enums
  - methods and local functions (constructors are not indexed, same as Java)
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
                return Helper.IsValid<string>(token);
            }

            int Total() {
                int Add(int a) => a + 1;
                return Add(1);
            }
        }
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
        assert {"IVerifier", "UserDto", "Point", "Status", "TokenService"} <= classes

    def test_methods_and_local_functions_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        functions = {s["name"] for s in syms if s["type"] == "FUNCTION"}
        assert {"Verify", "Total", "Add"} <= functions

    def test_constructor_not_indexed_as_function(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        assert not any(s["name"] == "TokenService" and s["type"] == "FUNCTION" for s in syms)

    def test_calls_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        verify = next(s for s in syms if s["name"] == "Verify" and s["start_line"] == 10)
        assert {"Check", "Decode", "IsValid"} <= set(verify["calls"])
        assert "Add" in _by_name(syms, "Total", "FUNCTION")["calls"]

    def test_base_list_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        assert _by_name(syms, "TokenService", "CLASS")["bases"] == ["BaseService", "IVerifier"]

    def test_index_repo_reports_csharp(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "TokenService.cs", _CS_SRC)
        summary = fresh_indexer.index_repo(str(tmp_path))
        assert summary["symbols"] > 0
        assert "C#" in summary["languages"]


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
