# SPDX-FileCopyrightText: 2026 Ashlesh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/your-username/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tests/test_indexer_multilang.py — Sprint 2.1 acceptance criteria.

Tests are structured so the Python baseline always runs (no grammar extras
needed), while language-specific tests skip gracefully with a helpful message
when the corresponding grammar package is not installed.

Covered:
  - Python file: 3 functions extracted (baseline, always runs)
  - JS file: function and arrow function extracted
             (pytest.importorskip("tree_sitter_javascript"))
  - Java file: class and method extracted
               (pytest.importorskip("tree_sitter_java"))
  - Unsupported .rb file: returns [], no exception
  - Missing grammar package: returns [], debug log, no crash
  - supported_extensions() returns only installed grammars
  - index_repo summary has per-language file counts
  - lookup_symbol() works for a JS function by name
"""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def fresh_indexer(isolated_cognirepo):
    """Return an ASTIndexer wired to an empty KnowledgeGraph."""
    from graph.knowledge_graph import KnowledgeGraph
    from indexer.ast_indexer import ASTIndexer
    from indexer.language_registry import clear_cache
    clear_cache()
    kg = KnowledgeGraph()
    return ASTIndexer(graph=kg)


def _write(tmp: Path, name: str, content: str) -> Path:
    p = tmp / name
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


# ── Python baseline (always runs — stdlib ast fallback) ───────────────────────

class TestPythonBaseline:
    """Verifies Python indexing works with or without tree-sitter-python."""

    def test_three_functions_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "sample.py", """\
            def alpha():
                pass

            def beta(x, y):
                return x + y

            def gamma():
                return alpha() + beta(1, 2)

            class MyClass:
                pass
        """)
        record = fresh_indexer.index_file("sample.py", str(src))
        symbols = record["symbols"]
        names = [s["name"] for s in symbols]
        assert "alpha" in names
        assert "beta" in names
        assert "gamma" in names

    def test_class_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "cls.py", """\
            class Widget:
                def render(self):
                    pass
        """)
        record = fresh_indexer.index_file("cls.py", str(src))
        names = [s["name"] for s in record["symbols"]]
        assert "Widget" in names
        assert "render" in names

    def test_calls_extracted_for_python(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "calls.py", """\
            def caller():
                helper()
                obj.method()
        """)
        record = fresh_indexer.index_file("calls.py", str(src))
        caller_sym = next(s for s in record["symbols"] if s["name"] == "caller")
        assert "helper" in caller_sym["calls"]
        assert "method" in caller_sym["calls"]

    def test_unsupported_file_returns_empty(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        rb = tmp_path / "script.rb"
        rb.write_text("def hello; end\n")
        record = fresh_indexer.index_file("script.rb", str(rb))
        assert record == {}

    def test_syntax_error_py_returns_empty_symbols(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        bad = _write(tmp_path, "bad.py", "def (broken:\n")
        record = fresh_indexer.index_file("bad.py", str(bad))
        assert record.get("symbols", []) == []

    def test_sha256_cache_skip(self, fresh_indexer, tmp_path, monkeypatch):
        """Re-indexing unchanged file returns existing record without mutation."""
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "cached.py", "def foo(): pass\n")
        r1 = fresh_indexer.index_file("cached.py", str(src))
        r2 = fresh_indexer.index_file("cached.py", str(src))
        assert r1["sha256"] == r2["sha256"]
        assert len(r2["symbols"]) == len(r1["symbols"])

    def test_lookup_symbol_after_index(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "lookup.py", "def find_me(): pass\n")
        fresh_indexer.index_file("lookup.py", str(src))
        fresh_indexer._build_reverse_index()
        results = fresh_indexer.lookup_symbol("find_me")
        assert len(results) == 1
        assert results[0]["file"] == "lookup.py"
        assert results[0]["line"] == 1


# ── JavaScript (tree-sitter-javascript) ──────────────────────────────────────

class TestJavaScriptIndexing:
    def test_js_function_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        pytest.importorskip("tree_sitter_javascript")
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "app.js", """\
            function verifyToken(token) {
                return jwt.verify(token, SECRET);
            }

            class AuthService {
                login(user) {}
            }
        """)
        record = fresh_indexer.index_file("app.js", str(src))
        names = [s["name"] for s in record["symbols"]]
        assert "verifyToken" in names
        assert "AuthService" in names

    def test_lookup_js_symbol(self, fresh_indexer, tmp_path, monkeypatch):
        """lookup_symbol returns correct file+line for a JS function."""
        pytest.importorskip("tree_sitter_javascript")
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "auth.js", """\
            function verifyToken(tok) {
                return tok;
            }
        """)
        fresh_indexer.index_file("auth.js", str(src))
        fresh_indexer._build_reverse_index()
        results = fresh_indexer.lookup_symbol("verifyToken")
        assert len(results) >= 1
        assert results[0]["file"] == "auth.js"
        assert results[0]["line"] == 1

    def test_ts_file_indexed(self, fresh_indexer, tmp_path, monkeypatch):
        pytest.importorskip("tree_sitter_javascript")
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "utils.ts", """\
            function parseDate(s: string): Date {
                return new Date(s);
            }
        """)
        record = fresh_indexer.index_file("utils.ts", str(src))
        names = [s["name"] for s in record["symbols"]]
        assert "parseDate" in names


# ── Java (tree-sitter-java) ───────────────────────────────────────────────────

class TestJavaIndexing:
    def test_java_class_and_method_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        pytest.importorskip("tree_sitter_java")
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "Service.java", """\
            public class UserService {
                public String findById(String id) {
                    return repository.find(id);
                }
            }
        """)
        record = fresh_indexer.index_file("Service.java", str(src))
        names = [s["name"] for s in record["symbols"]]
        assert "UserService" in names
        assert "findById" in names

    def test_java_lookup_method(self, fresh_indexer, tmp_path, monkeypatch):
        pytest.importorskip("tree_sitter_java")
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "Repo.java", """\
            public class Repo {
                public void save(Object obj) {}
            }
        """)
        fresh_indexer.index_file("Repo.java", str(src))
        fresh_indexer._build_reverse_index()
        results = fresh_indexer.lookup_symbol("save")
        assert any(r["file"] == "Repo.java" for r in results)


# ── language_registry ─────────────────────────────────────────────────────────

class TestLanguageRegistry:
    def test_supported_extensions_includes_python(self):
        """Python is always in supported_extensions (stdlib fallback)."""
        from indexer.language_registry import supported_extensions, clear_cache
        clear_cache()
        exts = supported_extensions()
        assert ".py" in exts

    def test_unsupported_ext_not_in_supported(self):
        from indexer.language_registry import _get_language, clear_cache
        clear_cache()
        lang = _get_language(".rb")
        assert lang is None

    def test_missing_grammar_returns_none_no_crash(self, monkeypatch):
        """Importing a non-existent grammar package must not raise."""
        import importlib
        from indexer.language_registry import clear_cache
        clear_cache()

        original_import = importlib.import_module

        def patched_import(name, *args, **kwargs):
            if name == "tree_sitter_java":
                raise ImportError("simulated missing package")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", patched_import)

        from indexer import language_registry
        clear_cache()

        lang = language_registry._get_language(".java")
        assert lang is None  # no crash, returns None

    def test_is_supported_python_always_true(self):
        from indexer.language_registry import is_supported, clear_cache
        clear_cache()
        assert is_supported(Path("anything.py")) is True

    def test_is_supported_ruby_false(self):
        from indexer.language_registry import is_supported
        assert is_supported(Path("script.rb")) is False


# ── index_repo summary ────────────────────────────────────────────────────────

class TestIndexRepoSummary:
    def test_summary_has_language_counts(self, fresh_indexer, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "a.py", "def foo(): pass\n")
        _write(tmp_path, "b.py", "def bar(): pass\n")

        summary = fresh_indexer.index_repo(str(tmp_path))
        out = capsys.readouterr().out

        assert summary["files"] == 2
        assert "Python" in summary["languages"]
        assert summary["languages"]["Python"] == 2
        assert "Python" in out

    def test_summary_skips_unsupported_exts(self, fresh_indexer, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "main.py", "def entry(): pass\n")
        (tmp_path / "data.rb").write_text("def hello; end\n")

        summary = fresh_indexer.index_repo(str(tmp_path))
        out = capsys.readouterr().out

        # .rb should appear in skipped extensions
        assert ".rb" in summary["skipped_extensions"]
        assert ".rb" in out or "Unsupported" in out

    def test_summary_symbol_count(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "funcs.py", "def a(): pass\ndef b(): pass\ndef c(): pass\n")
        summary = fresh_indexer.index_repo(str(tmp_path))
        assert summary["symbols"] >= 3
