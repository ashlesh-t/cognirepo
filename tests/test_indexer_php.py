# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_indexer_php.py — PHP (.php) indexing via tree-sitter-php (#73).

Covers:
  - classes, interfaces, traits, enums, functions and methods
  - call extraction for foo(), $obj->foo() and Foo::bar()
  - `extends` base extraction
  - files mixing inline HTML with <?php blocks
  - registry / service-marker wiring
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("tree_sitter_php")


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


_PHP_SRC = """\
    <?php
    namespace App;

    interface Verifier { public function verify($token); }

    trait Logs {
        function log($msg) { error_log($msg); }
    }

    class TokenService extends BaseService implements Verifier {
        public function verify($token) {
            $this->decode($token);
            Helper::check($token);
            return strlen($token) > 0;
        }
    }

    enum Status { case Active; }

    function build_service() { return new TokenService(); }
"""


def _symbols(fresh_indexer, tmp_path, monkeypatch) -> list[dict]:
    monkeypatch.chdir(tmp_path)
    src = _write(tmp_path, "TokenService.php", _PHP_SRC)
    record = fresh_indexer.index_file("TokenService.php", str(src))
    return record["symbols"]


def _by_name(symbols: list[dict], name: str, line: int) -> dict:
    return next(s for s in symbols if s["name"] == name and s["start_line"] == line)


class TestPhpIndexing:
    def test_type_declarations_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        classes = {s["name"] for s in syms if s["type"] == "CLASS"}
        assert {"Verifier", "Logs", "TokenService", "Status"} <= classes

    def test_functions_and_methods_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        functions = {s["name"] for s in syms if s["type"] == "FUNCTION"}
        assert {"verify", "log", "build_service"} <= functions

    def test_calls_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        verify = _by_name(syms, "verify", 11)
        assert {"decode", "check", "strlen"} <= set(verify["calls"])
        assert "error_log" in _by_name(syms, "log", 7)["calls"]

    def test_extends_base_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        assert _by_name(syms, "TokenService", 10)["bases"] == ["BaseService"]

    def test_inline_html_file_parses(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "view.php", """\
            <html><body>
            <?php function render_title($t) { echo htmlspecialchars($t); } ?>
            </body></html>
        """)
        record = fresh_indexer.index_file("view.php", str(src))
        fn = next(s for s in record["symbols"] if s["name"] == "render_title")
        assert "htmlspecialchars" in fn["calls"]

    def test_index_repo_reports_php(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "TokenService.php", _PHP_SRC)
        summary = fresh_indexer.index_repo(str(tmp_path))
        assert summary["symbols"] > 0
        assert "PHP" in summary["languages"]


class TestPhpRegistry:
    def test_grammar_mapped(self):
        from intelligence.indexer.language_registry import (
            _GRAMMAR_FUNC_OVERRIDE, _GRAMMAR_MAP, lang_label, lang_name,
        )
        assert _GRAMMAR_MAP[".php"] == "tree_sitter_php"
        assert _GRAMMAR_FUNC_OVERRIDE[".php"] == ("tree_sitter_php", "language_php")
        assert lang_label(".php") == "PHP"
        assert lang_name(".php") == "php"

    def test_php_supported(self):
        from intelligence.indexer.language_registry import is_supported, clear_cache
        clear_cache()
        assert is_supported(Path("index.php")) is True

    def test_composer_service_marker(self):
        from interface.cli.service_detect import _SERVICE_MARKERS
        assert _SERVICE_MARKERS["composer.json"][1] == "PHP"

    def test_semantic_search_language_filter(self):
        from interface.tools.semantic_search_code import _lang_extensions
        assert _lang_extensions("php") == {".php"}
