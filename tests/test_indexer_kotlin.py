# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_indexer_kotlin.py — Kotlin (.kt / .kts) indexing via tree-sitter-kotlin (#178).

Covers:
  - classes, interfaces, data/enum classes, objects and companion objects
  - functions, extension functions, secondary constructors and init blocks
  - call extraction for foo(), a.b(), a?.b() and trailing-lambda calls
  - supertype extraction (qualified names, constructor calls, `by` delegation)
  - registry / build.gradle.kts service-marker wiring
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("tree_sitter_kotlin")


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


_KOTLIN_SRC = """\
    package com.example.auth

    interface Verifier {
        fun verify(token: String): Boolean
    }

    data class Token(val raw: String)

    enum class Status {
        ACTIVE
    }

    class TokenService(private val helper: Helper) : com.example.core.BaseService(), Verifier {
        constructor() : this(Helper()) {
            setup()
        }

        init {
            warmUp()
        }

        override fun verify(token: String): Boolean {
            helper.check(token)
            helper?.audit(token)
            decode(token)
            listOf(token).forEach { log(it) }
            return Helper.isValid(token)
        }

        companion object {
            fun create(): TokenService = TokenService()
        }
    }

    object Registry {
        fun register(svc: TokenService) {
            this.track(svc)
        }
    }

    fun String.toToken(): Token = Token(this)
"""


def _symbols(fresh_indexer, tmp_path, monkeypatch) -> list[dict]:
    monkeypatch.chdir(tmp_path)
    src = _write(tmp_path, "TokenService.kt", _KOTLIN_SRC)
    record = fresh_indexer.index_file("TokenService.kt", str(src))
    return record["symbols"]


def _by_name(symbols: list[dict], name: str, line: int) -> dict:
    return next(s for s in symbols if s["name"] == name and s["start_line"] == line)


class TestKotlinIndexing:
    def test_type_declarations_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        classes = {s["name"] for s in syms if s["type"] == "CLASS"}
        assert {"Verifier", "Token", "Status", "TokenService", "Registry"} <= classes

    def test_unnamed_companion_object_is_companion(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        assert _by_name(syms, "Companion", 30)["type"] == "CLASS"

    def test_named_companion_object_keeps_its_name(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "User.kt", """\
            class User {
                companion object Factory {
                    fun make(): User = User()
                }
            }
        """)
        record = fresh_indexer.index_file("User.kt", str(src))
        assert ("Factory", "CLASS") in {(s["name"], s["type"]) for s in record["symbols"]}

    def test_functions_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        functions = {(s["name"], s["start_line"]) for s in syms if s["type"] == "FUNCTION"}
        assert {
            ("verify", 4), ("constructor", 14), ("init", 18), ("verify", 22),
            ("create", 31), ("register", 36), ("toToken", 41),
        } <= functions

    def test_constructor_and_init_calls_attributed(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        assert "setup" in _by_name(syms, "constructor", 14)["calls"]
        assert "warmUp" in _by_name(syms, "init", 18)["calls"]

    def test_calls_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        calls = set(_by_name(syms, "verify", 22)["calls"])
        # plain, qualified, safe-call, static-style and trailing-lambda forms
        assert {"check", "audit", "decode", "listOf", "forEach", "log", "isValid"} <= calls
        assert "track" in _by_name(syms, "register", 36)["calls"]

    def test_no_false_calls_for_keywords(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "Flow.kt", """\
            class Flow(val a: A) {
                fun run(): Int {
                    if (a.ok()) return 1
                    when (a) {
                        is A -> handle()
                        else -> throw IllegalStateException("x")
                    }
                    super.toString()
                    val ref = ::helper
                    return@run 0
                }
            }
        """)
        record = fresh_indexer.index_file("Flow.kt", str(src))
        run = next(s for s in record["symbols"] if s["name"] == "run")
        assert set(run["calls"]) == {"ok", "handle", "IllegalStateException", "toString"}

    def test_supertypes_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        syms = _symbols(fresh_indexer, tmp_path, monkeypatch)
        # `com.example.core.BaseService()` normalised to its simple name
        assert _by_name(syms, "TokenService", 13)["bases"] == ["BaseService", "Verifier"]

    def test_generic_and_delegated_supertypes(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "Repo.kt", """\
            class Repo(store: Store) : Store by store, Comparable<Repo>, a.b.Closeable {
                override fun compareTo(other: Repo): Int = 0
            }
        """)
        record = fresh_indexer.index_file("Repo.kt", str(src))
        repo = next(s for s in record["symbols"] if s["name"] == "Repo")
        assert repo["bases"] == ["Store", "Comparable", "Closeable"]

    def test_build_output_dirs_skipped(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "TokenService.kt", _KOTLIN_SRC)
        for d in ("build/generated/source", ".gradle/kotlin"):
            (tmp_path / d).mkdir(parents=True)
            _write(tmp_path / d, "Generated.kt", "fun generated() {}\n")
        fresh_indexer.index_repo(str(tmp_path))
        assert list(fresh_indexer.index_data["files"]) == ["TokenService.kt"]

    def test_kts_script_indexed(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "tasks.kts", """\
            fun configure() {
                apply("plugin")
            }
        """)
        record = fresh_indexer.index_file("tasks.kts", str(src))
        configure = next(s for s in record["symbols"] if s["name"] == "configure")
        assert "apply" in configure["calls"]

    def test_index_repo_reports_kotlin(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "TokenService.kt", _KOTLIN_SRC)
        summary = fresh_indexer.index_repo(str(tmp_path))
        assert summary["symbols"] > 0
        assert "Kotlin" in summary["languages"]


class TestSharedCallExpressionBranch:
    """The Kotlin callee fallback lives in the shared `call_expression` branch — pin that
    JS/TS/Go/Swift call extraction is unchanged by it."""

    @pytest.mark.parametrize("ext, grammar, code, expected", [
        (".js", "tree_sitter_javascript",
         b"function f() { foo(); obj.bar(); a.b.baz(); }", {"foo", "bar", "baz"}),
        (".ts", "tree_sitter_typescript",
         b"function f(): void { foo(); obj.bar<T>(); }", {"foo", "bar"}),
        (".go", "tree_sitter_go",
         b"package m\nfunc f() { foo(); obj.Bar(); Svc.Run() }", {"foo", "Bar", "Run", "Svc::Run"}),
        (".swift", "tree_sitter_swift",
         b"func f() { foo(); obj.bar(); A.b.baz() }", {"foo", "bar", "baz"}),
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


class TestKotlinRegistry:
    def test_grammar_mapped(self):
        from intelligence.indexer.language_registry import _GRAMMAR_MAP, lang_label, lang_name
        for ext in (".kt", ".kts"):
            assert _GRAMMAR_MAP[ext] == "tree_sitter_kotlin"
            assert lang_label(ext) == "Kotlin"
            assert lang_name(ext) == "kotlin"

    def test_kotlin_supported(self):
        from intelligence.indexer.language_registry import is_supported, clear_cache
        clear_cache()
        assert is_supported(Path("Main.kt")) is True
        assert is_supported(Path("build.gradle.kts")) is True

    def test_kotlin_in_post_commit_extensions(self):
        from intelligence.indexer.language_registry import known_extensions
        assert {".kt", ".kts"} <= set(known_extensions())

    def test_build_gradle_kts_service_marker(self, tmp_path):
        from interface.cli.service_detect import _SERVICE_MARKERS, detect_sub_repos
        assert _SERVICE_MARKERS["build.gradle.kts"] == ("rest_api", "Kotlin/Gradle")
        svc = tmp_path / "billing-service"
        svc.mkdir()
        (svc / "build.gradle.kts").write_text('plugins { kotlin("jvm") }\n')
        found = detect_sub_repos(str(tmp_path))
        assert [c.name for c in found] == ["billing-service"]

    def test_semantic_search_language_filter(self):
        from interface.tools.semantic_search_code import _lang_extensions
        assert _lang_extensions("kotlin") == {".kt", ".kts"}
