# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_indexer_ruby.py — Ruby (.rb) indexing via tree-sitter-ruby (#72).

Covers:
  - classes, modules, instance methods and singleton (def self.x) methods
  - call extraction for bare, receiver and scoped calls
  - superclass extraction (plain and Mod::Class)
  - Ruby-only node types (`class`, `module`) do not leak into other grammars
  - registry / service-marker wiring
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("tree_sitter_ruby")


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


_RUBY_SRC = """\
    module Auth
      class TokenService < BaseService
        def verify(token)
          decode(token)
          helper.check(token)
          Codec::strip(token)
        end

        def self.build
          new
        end
      end

      class AdminService < Auth::TokenService
      end
    end
"""


def _symbols(fresh_indexer, tmp_path, monkeypatch) -> dict[str, dict]:
    monkeypatch.chdir(tmp_path)
    src = _write(tmp_path, "token_service.rb", _RUBY_SRC)
    record = fresh_indexer.index_file("token_service.rb", str(src))
    return {s["name"]: s for s in record["symbols"]}


class TestRubyIndexing:
    def test_classes_and_modules_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        assert syms["Auth"]["type"] == "CLASS"
        assert syms["TokenService"]["type"] == "CLASS"
        assert syms["AdminService"]["type"] == "CLASS"

    def test_instance_and_singleton_methods_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        assert syms["verify"]["type"] == "FUNCTION"
        assert syms["verify"]["start_line"] == 3
        assert syms["build"]["type"] == "FUNCTION"

    def test_calls_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        assert {"decode", "check", "strip"} <= set(syms["verify"]["calls"])

    def test_superclass_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        assert syms["TokenService"]["bases"] == ["BaseService"]
        # Namespaced bases are reduced to their last segment so they resolve by simple name
        assert syms["AdminService"]["bases"] == ["TokenService"]

    def test_namespaced_inherits_edge_lands_on_simple_symbol(
        self, fresh_indexer, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "token_service.rb", _RUBY_SRC)
        fresh_indexer.index_file("token_service.rb", str(src))
        from data.graph.knowledge_graph import EdgeType
        g = fresh_indexer.graph.G
        inherits = [
            dst for src_node, dst, data in g.edges(data=True)
            if data.get("rel") == EdgeType.INHERITS and "AdminService" in src_node
        ]
        assert "symbol::TokenService" in inherits

    def test_class_and_new_not_recorded_as_calls(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "builder.rb", """\
            class Builder
              def make
                self.class.build
                Widget.new(1)
              end
            end
        """)
        record = fresh_indexer.index_file("builder.rb", str(src))
        calls = {s["name"]: s for s in record["symbols"]}["make"]["calls"]
        assert "build" in calls
        assert "class" not in calls
        assert "new" not in calls

    def test_index_repo_reports_ruby(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "token_service.rb", _RUBY_SRC)
        summary = fresh_indexer.index_repo(str(tmp_path))
        assert summary["symbols"] > 0
        assert "Ruby" in summary["languages"]


class TestRubyNodeTypesScoped:
    def test_ts_module_block_not_indexed_as_class(self):
        """Ruby's `module` node type must not turn TS `module Foo {}` into a CLASS."""
        pytest.importorskip("tree_sitter_typescript")
        from tree_sitter import Parser
        from intelligence.indexer.ast_indexer import _extract_symbols_ts
        from intelligence.indexer.language_registry import _get_language, clear_cache
        clear_cache()
        code = b"module Foo { export function f() {} }\n"
        tree = Parser(_get_language(".ts")).parse(code)
        names = [(s["type"], s["name"]) for s in _extract_symbols_ts(tree, code, ".ts")]
        assert ("CLASS", "Foo") not in names
        assert ("FUNCTION", "f") in names


class TestRubyRegistry:
    def test_grammar_mapped(self):
        from intelligence.indexer.language_registry import _GRAMMAR_MAP, lang_label, lang_name
        assert _GRAMMAR_MAP[".rb"] == "tree_sitter_ruby"
        assert lang_label(".rb") == "Ruby"
        assert lang_name(".rb") == "ruby"

    def test_rb_supported(self):
        from intelligence.indexer.language_registry import is_supported, clear_cache
        clear_cache()
        assert is_supported(Path("app.rb")) is True

    def test_gemfile_service_marker(self):
        from interface.cli.service_detect import _SERVICE_MARKERS
        assert _SERVICE_MARKERS["Gemfile"][1] == "Ruby"
