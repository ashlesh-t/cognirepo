# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under AGPL v3. See LICENSE file in repository root.

"""
tests/test_multilang_indexer.py — Sprint 2 acceptance tests.

Covers:
  - TypeScript (.ts) indexing with tree-sitter-typescript grammar
  - TSX (.tsx) indexing
  - Go (.go) indexing
  - Rust (.rs) indexing
  - language_registry correctly dispatches .ts/.tsx to TypeScript grammar
  - Watchdog covers all indexed extensions (not just .py)
  - hybrid cache invalidated on watchdog events
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def fresh_indexer(isolated_cognirepo):
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


# ── TypeScript ─────────────────────────────────────────────────────────────────

class TestTypeScriptIndexing:
    def test_ts_function_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        pytest.importorskip("tree_sitter_typescript")
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "auth.ts", """\
            function verifyToken(token: string): boolean {
                return jwt.verify(token, SECRET);
            }

            class AuthService {
                login(user: string): void {}
            }
        """)
        record = fresh_indexer.index_file("auth.ts", str(src))
        names = [s["name"] for s in record["symbols"]]
        assert "verifyToken" in names
        assert "AuthService" in names

    def test_ts_interface_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        pytest.importorskip("tree_sitter_typescript")
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "types.ts", """\
            interface UserProfile {
                id: string;
                name: string;
            }
        """)
        record = fresh_indexer.index_file("types.ts", str(src))
        names = [s["name"] for s in record["symbols"]]
        assert "UserProfile" in names

    def test_tsx_function_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        pytest.importorskip("tree_sitter_typescript")
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "Button.tsx", """\
            function Button(props: ButtonProps) {
                return null;
            }

            class FormComponent {
                render() {}
            }
        """)
        record = fresh_indexer.index_file("Button.tsx", str(src))
        names = [s["name"] for s in record["symbols"]]
        assert "Button" in names or "FormComponent" in names

    def test_lookup_ts_symbol(self, fresh_indexer, tmp_path, monkeypatch):
        pytest.importorskip("tree_sitter_typescript")
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "service.ts", """\
            function fetchUserProfile(userId: string) {
                return api.get(`/users/${userId}`);
            }
        """)
        fresh_indexer.index_file("service.ts", str(src))
        fresh_indexer._build_reverse_index()
        results = fresh_indexer.lookup_symbol("fetchUserProfile")
        assert len(results) >= 1
        assert results[0]["file"] == "service.ts"

    def test_ts_uses_typescript_grammar_not_javascript(self):
        """Verify .ts dispatches to tree_sitter_typescript, not tree_sitter_javascript."""
        pytest.importorskip("tree_sitter_typescript")
        from indexer.language_registry import _get_language, clear_cache
        import tree_sitter_typescript
        clear_cache()
        lang = _get_language(".ts")
        assert lang is not None
        # The language object should correspond to the TypeScript grammar
        ts_lang_obj = __import__("tree_sitter").Language(
            tree_sitter_typescript.language_typescript()
        )
        assert lang == ts_lang_obj


# ── Go ─────────────────────────────────────────────────────────────────────────

class TestGoIndexing:
    def test_go_function_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        pytest.importorskip("tree_sitter_go")
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "auth.go", """\
            package auth

            func VerifyToken(token string) bool {
                return true
            }

            func HashPassword(pw string) string {
                return pw
            }
        """)
        record = fresh_indexer.index_file("auth.go", str(src))
        names = [s["name"] for s in record["symbols"]]
        assert "VerifyToken" in names
        assert "HashPassword" in names

    def test_lookup_go_symbol(self, fresh_indexer, tmp_path, monkeypatch):
        pytest.importorskip("tree_sitter_go")
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "router.go", """\
            package router

            func HandleRequest(w http.ResponseWriter, r *http.Request) {
                w.Write([]byte("ok"))
            }
        """)
        fresh_indexer.index_file("router.go", str(src))
        fresh_indexer._build_reverse_index()
        results = fresh_indexer.lookup_symbol("HandleRequest")
        assert len(results) >= 1
        assert results[0]["file"] == "router.go"

    def test_go_symbol_count_positive(self, fresh_indexer, tmp_path, monkeypatch, capsys):
        pytest.importorskip("tree_sitter_go")
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "main.go", """\
            package main

            func main() {}
            func init() {}
        """)
        summary = fresh_indexer.index_repo(str(tmp_path))
        assert summary["symbols"] > 0
        assert "Go" in summary["languages"]


# ── Rust ──────────────────────────────────────────────────────────────────────

class TestRustIndexing:
    def test_rust_function_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        pytest.importorskip("tree_sitter_rust")
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "lib.rs", """\
            fn verify_token(token: &str) -> bool {
                true
            }

            struct AuthService {
                secret: String,
            }
        """)
        record = fresh_indexer.index_file("lib.rs", str(src))
        names = [s["name"] for s in record["symbols"]]
        assert "verify_token" in names
        assert "AuthService" in names


# ── Language registry ─────────────────────────────────────────────────────────

class TestLanguageRegistryV2:
    def test_ts_grammar_is_typescript_not_javascript(self):
        """language_registry must NOT map .ts to tree_sitter_javascript."""
        from indexer.language_registry import _GRAMMAR_MAP
        assert _GRAMMAR_MAP.get(".ts") == "tree_sitter_typescript"
        assert _GRAMMAR_MAP.get(".tsx") == "tree_sitter_typescript"

    def test_tsx_uses_tsx_function(self):
        pytest.importorskip("tree_sitter_typescript")
        from indexer.language_registry import _GRAMMAR_FUNC_OVERRIDE
        assert ".ts" in _GRAMMAR_FUNC_OVERRIDE
        assert _GRAMMAR_FUNC_OVERRIDE[".ts"][1] == "language_typescript"
        assert ".tsx" in _GRAMMAR_FUNC_OVERRIDE
        assert _GRAMMAR_FUNC_OVERRIDE[".tsx"][1] == "language_tsx"

    def test_ts_lang_name_is_typescript(self):
        from indexer.language_registry import lang_name
        assert lang_name(".ts") == "typescript"
        assert lang_name(".tsx") == "tsx"

    def test_go_supported(self):
        pytest.importorskip("tree_sitter_go")
        from indexer.language_registry import is_supported, clear_cache
        clear_cache()
        assert is_supported(Path("main.go")) is True

    def test_rust_supported(self):
        pytest.importorskip("tree_sitter_rust")
        from indexer.language_registry import is_supported, clear_cache
        clear_cache()
        assert is_supported(Path("lib.rs")) is True


# ── Watchdog multi-extension coverage ────────────────────────────────────────

class TestWatchdogCoverage:
    def _make_handler(self):
        from indexer.file_watcher import RepoFileHandler
        indexer = MagicMock()
        indexer.index_data = {"files": {}, "reverse_index": {}}
        graph = MagicMock()
        graph.nodes_for_file.return_value = []
        behaviour = MagicMock()
        return RepoFileHandler(
            repo_root="/repo",
            indexer=indexer,
            graph=graph,
            behaviour=behaviour,
            session_id="test",
        )

    @pytest.mark.parametrize("ext", [".ts", ".tsx", ".go", ".rs", ".java", ".py"])
    def test_supported_extensions_trigger_reindex(self, ext, tmp_path):
        """on_modified must trigger _reindex for each indexed extension."""
        from watchdog.events import FileModifiedEvent
        handler = self._make_handler()

        fake_file = tmp_path / f"file{ext}"
        fake_file.write_text("// content")

        with patch.object(handler, "_reindex") as mock_reindex:
            event = FileModifiedEvent(str(fake_file))
            handler.on_modified(event)

        mock_reindex.assert_called_once_with(str(fake_file))

    def test_unsupported_ext_not_triggered(self, tmp_path):
        """on_modified must NOT trigger _reindex for unsupported extensions."""
        from watchdog.events import FileModifiedEvent
        handler = self._make_handler()

        fake_file = tmp_path / "file.rb"
        fake_file.write_text("# ruby")

        with patch.object(handler, "_reindex") as mock_reindex:
            event = FileModifiedEvent(str(fake_file))
            handler.on_modified(event)

        mock_reindex.assert_not_called()

    def test_cache_invalidated_on_reindex(self, tmp_path):
        """After _reindex, invalidate_hybrid_cache must be called."""
        from indexer.file_watcher import RepoFileHandler
        indexer = MagicMock()
        indexer.index_data = {"files": {}, "reverse_index": {}}
        graph = MagicMock()
        graph.nodes_for_file.return_value = []
        behaviour = MagicMock()
        handler = RepoFileHandler("/repo", indexer, graph, behaviour, "test")

        fake_file = tmp_path / "module.py"
        fake_file.write_text("def foo(): pass")

        with patch("indexer.file_watcher.RepoFileHandler._reindex", wraps=handler._reindex):
            with patch("retrieval.hybrid.invalidate_hybrid_cache") as mock_inv:
                with patch("os.path.relpath", return_value="module.py"):
                    handler._reindex(str(fake_file))

        mock_inv.assert_called_once()

    def test_cache_invalidated_on_remove(self, tmp_path):
        """After _remove, invalidate_hybrid_cache must be called."""
        from indexer.file_watcher import RepoFileHandler
        indexer = MagicMock()
        indexer.index_data = {"files": {"module.py": {}}, "reverse_index": {}}
        graph = MagicMock()
        graph.nodes_for_file.return_value = []
        behaviour = MagicMock()
        handler = RepoFileHandler("/repo", indexer, graph, behaviour, "test")

        with patch("retrieval.hybrid.invalidate_hybrid_cache") as mock_inv:
            with patch("os.path.relpath", return_value="module.py"):
                handler._remove("/repo/module.py")

        mock_inv.assert_called_once()
