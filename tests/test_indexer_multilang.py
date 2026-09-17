# pylint: disable=missing-docstring, unnecessary-lambda, import-outside-toplevel, too-few-public-methods, duplicate-code
# pylint: disable=redefined-outer-name, unused-argument, broad-exception-caught, protected-access
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

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

import textwrap
from pathlib import Path

import pytest


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def fresh_indexer(isolated_cognirepo):
    """Return an ASTIndexer wired to an empty KnowledgeGraph."""
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
        if "symbols" not in record:
            pytest.skip("TS grammar installed but no symbols extracted — grammar may not support TypeScript")
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


# ── Go (tree-sitter-go) ────────────────────────────────────────────────────────

def _callers_of(graph, name: str) -> list[str]:
    """Mirror of interface/server/mcp_server.py::who_calls's graph-only lookup —
    successors of the symbol/stub-resolved node connected via a CALLS edge."""
    from data.graph.knowledge_graph import EdgeType
    node = f"symbol::{name}"
    if not graph.G.has_node(node):
        candidates = [
            n for n in graph.G.nodes()
            if n.endswith(f"::{name}") and not n.startswith("symbol::")
        ]
        if not candidates:
            return []
        node = candidates[0]
    return [
        succ for succ in graph.G.successors(node)
        if graph.G[node][succ].get("rel") == EdgeType.CALLS
    ]


class TestGoIndexing:
    """COGNIREPO-203 AC1 — Go selector_expression (receiver-qualified method) calls
    must resolve through who_calls, not just plain function calls."""

    _GO_FIXTURE = """\
        package main

        type Server struct{}

        func (s *Server) Start() {
            s.listen()
            logStart()
        }

        func (s *Server) listen() {
            accept()
        }

        func (s *Server) Stop() {
            s.cleanup()
        }

        func (s *Server) cleanup() {}

        func accept() {
            handle()
        }

        func handle() {
            process()
        }

        func process() {
            validate()
            save()
        }

        func validate() {}
        func save() {}
        func logStart() {}

        func main() {
            s := &Server{}
            s.Start()
            s.Stop()
            setup()
        }

        func setup() {}
    """

    # Hand-verified callee -> caller pairs (11 call sites, per AC1's "≥10 incl. method calls").
    _EXPECTED_CALLERS = {
        "listen": "Start", "logStart": "Start", "cleanup": "Stop", "accept": "listen",
        "handle": "accept", "process": "handle", "validate": "process", "save": "process",
        "Start": "main", "Stop": "main", "setup": "main",
    }

    def test_go_functions_and_methods_extracted(self, fresh_indexer, tmp_path, monkeypatch):
        pytest.importorskip("tree_sitter_go")
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "main.go", self._GO_FIXTURE)
        record = fresh_indexer.index_file("main.go", str(tmp_path / "main.go"))
        names = [s["name"] for s in record["symbols"]]
        assert "Server" in names
        assert "Start" in names and "listen" in names and "Stop" in names

    def test_go_selector_expression_call_captured(self, fresh_indexer, tmp_path, monkeypatch):
        """Regression guard for the field-vs-property tree-sitter bug: Go's
        selector_expression names its method field "field", not "property" (the JS
        name) — before the fix, `s.listen()` inside Start() was silently dropped."""
        pytest.importorskip("tree_sitter_go")
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "main.go", self._GO_FIXTURE)
        record = fresh_indexer.index_file("main.go", str(tmp_path / "main.go"))
        start_sym = next(s for s in record["symbols"] if s["name"] == "Start")
        assert "listen" in start_sym["calls"]

    def test_who_calls_resolves_at_least_90_percent_of_hand_verified_callers(
        self, fresh_indexer, tmp_path, monkeypatch
    ):
        pytest.importorskip("tree_sitter_go")
        monkeypatch.chdir(tmp_path)
        _write(tmp_path, "main.go", self._GO_FIXTURE)
        fresh_indexer.index_repo(str(tmp_path))

        resolved = 0
        for callee, expected_caller in self._EXPECTED_CALLERS.items():
            callers = _callers_of(fresh_indexer.graph, callee)
            if any(c.endswith(f"::{expected_caller}") for c in callers):
                resolved += 1
        ratio = resolved / len(self._EXPECTED_CALLERS)
        assert ratio >= 0.90, f"only {resolved}/{len(self._EXPECTED_CALLERS)} callers resolved"

    def test_go_imports_edge_to_local_package(self, fresh_indexer, tmp_path, monkeypatch):
        pytest.importorskip("tree_sitter_go")
        monkeypatch.chdir(tmp_path)
        (tmp_path / "go.mod").write_text("module example.com/demo\n\ngo 1.21\n", encoding="utf-8")
        util_dir = tmp_path / "util"
        util_dir.mkdir()
        _write(util_dir, "util.go", """\
            package util

            func Helper() {}
        """)
        _write(tmp_path, "main.go", """\
            package main

            import "example.com/demo/util"

            func main() {
                util.Helper()
            }
        """)
        from data.graph.knowledge_graph import EdgeType
        fresh_indexer.index_repo(str(tmp_path))
        assert fresh_indexer.graph.G.has_edge("main.go", "util/util.go")
        edge = fresh_indexer.graph.G["main.go"]["util/util.go"]
        assert edge.get("rel") == EdgeType.IMPORTS

    def test_go_external_import_not_resolved_locally(self, fresh_indexer, tmp_path, monkeypatch):
        """stdlib/third-party imports (no go.mod match) must not fabricate edges."""
        pytest.importorskip("tree_sitter_go")
        monkeypatch.chdir(tmp_path)
        (tmp_path / "go.mod").write_text("module example.com/demo\n\ngo 1.21\n", encoding="utf-8")
        _write(tmp_path, "main.go", """\
            package main

            import "fmt"

            func main() {
                fmt.Println("hi")
            }
        """)
        fresh_indexer.index_repo(str(tmp_path))
        file_node = fresh_indexer.graph.G.nodes.get("main.go", {})
        assert file_node  # file node itself still exists
        assert fresh_indexer.graph.G.out_degree("main.go") == 0


# ── Dynamic dispatch annotation (COGNIREPO-203 AC2) ────────────────────────────

class TestDynamicDispatchAnnotation:
    def test_celery_task_decorator_tagged_dynamic(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "tasks.py", """\
            from celery import shared_task

            @shared_task
            def send_email(to):
                pass

            @app.task
            def process_order(order_id):
                pass

            def plain_function():
                pass
        """)
        record = fresh_indexer.index_file("tasks.py", str(src))
        by_name = {s["name"]: s for s in record["symbols"]}
        assert by_name["send_email"]["dispatch"] == "dynamic"
        assert by_name["process_order"]["dispatch"] == "dynamic"
        assert by_name["plain_function"].get("dispatch") is None

    def test_register_call_tagged_dynamic(self, fresh_indexer, tmp_path, monkeypatch):
        """Generic plugin-registry pattern (Ansible-module-style self-registration)."""
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "plugins.py", """\
            def setup_plugin():
                registry.register(MyPlugin)
        """)
        record = fresh_indexer.index_file("plugins.py", str(src))
        sym = next(s for s in record["symbols"] if s["name"] == "setup_plugin")
        assert sym["dispatch"] == "dynamic"

    def test_init_subclass_tagged_dynamic(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = _write(tmp_path, "plugin_base.py", """\
            class PluginBase:
                def __init_subclass__(cls, **kwargs):
                    super().__init_subclass__(**kwargs)
        """)
        record = fresh_indexer.index_file("plugin_base.py", str(src))
        sym = next(s for s in record["symbols"] if s["name"] == "__init_subclass__")
        assert sym["dispatch"] == "dynamic"

    def test_dispatch_dynamic_relates_to_concept_node(self, fresh_indexer, tmp_path, monkeypatch):
        """dispatch:"dynamic" symbols get a RELATES_TO edge to the dynamic_dispatch
        CONCEPT node, so subgraph()/graph queries surface them without a fabricated
        CALLS edge (risk note: annotation-only)."""
        monkeypatch.chdir(tmp_path)
        from data.graph.knowledge_graph import EdgeType
        src = _write(tmp_path, "tasks.py", """\
            @shared_task
            def send_email(to):
                pass
        """)
        fresh_indexer.index_file("tasks.py", str(src))
        sym_node = "tasks.py::send_email"
        assert fresh_indexer.graph.G.nodes[sym_node].get("dispatch") == "dynamic"
        assert fresh_indexer.graph.G.has_edge(sym_node, "concept::dynamic_dispatch")
        assert fresh_indexer.graph.G[sym_node]["concept::dynamic_dispatch"]["rel"] == EdgeType.RELATES_TO

    def test_entry_points_pyproject_tagged_dynamic(self, fresh_indexer, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "pyproject.toml").write_text(
            """\
            [project.entry-points."myapp.plugins"]
            widget = "myapp.plugins.widget:load_widget"
            """,
            encoding="utf-8",
        )
        _write(tmp_path, "widget.py", """\
            def load_widget():
                pass
        """)
        fresh_indexer.index_repo(str(tmp_path))
        assert fresh_indexer.graph.G.nodes["widget.py::load_widget"].get("dispatch") == "dynamic"

    def test_no_fabricated_calls_edge_from_dispatch_tag(self, fresh_indexer, tmp_path, monkeypatch):
        """Risk note: dispatch heuristics are annotation-only — no synthetic CALLS
        edge should appear between a dispatch:"dynamic" symbol and anything else
        purely because of the tag."""
        monkeypatch.chdir(tmp_path)
        from data.graph.knowledge_graph import EdgeType
        src = _write(tmp_path, "tasks.py", """\
            @shared_task
            def send_email(to):
                pass
        """)
        fresh_indexer.index_file("tasks.py", str(src))
        sym_node = "tasks.py::send_email"
        rels = {
            fresh_indexer.graph.G[sym_node][succ].get("rel")
            for succ in fresh_indexer.graph.G.successors(sym_node)
        }
        assert EdgeType.CALLS not in rels


# ── language_registry ─────────────────────────────────────────────────────────

class TestLanguageRegistry:
    def test_supported_extensions_includes_python(self):
        """Python is always in supported_extensions (stdlib fallback)."""
        from intelligence.indexer.language_registry import supported_extensions, clear_cache
        clear_cache()
        exts = supported_extensions()
        assert ".py" in exts

    def test_unsupported_ext_not_in_supported(self):
        from intelligence.indexer.language_registry import _get_language, clear_cache
        clear_cache()
        lang = _get_language(".rb")
        assert lang is None

    def test_missing_grammar_returns_none_no_crash(self, monkeypatch):
        """Importing a non-existent grammar package must not raise."""
        import importlib
        from intelligence.indexer.language_registry import clear_cache
        clear_cache()

        original_import = importlib.import_module

        def patched_import(name, *args, **kwargs):
            if name == "tree_sitter_java":
                raise ImportError("simulated missing package")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", patched_import)

        from intelligence.indexer import language_registry
        clear_cache()

        lang = language_registry._get_language(".java")
        assert lang is None  # no crash, returns None

    def test_is_supported_python_always_true(self):
        from intelligence.indexer.language_registry import is_supported, clear_cache
        clear_cache()
        assert is_supported(Path("anything.py")) is True

    def test_is_supported_ruby_false(self):
        from intelligence.indexer.language_registry import is_supported
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


class TestLiteGraphWeightFilter:
    """COGNIREPO-500-D01 — a symbol below _graph_weight_min (lite-graph mode on large repos)
    still gets a minimal graph node + DEFINED_IN edge, so intelligence/retrieval/hybrid.py's
    independence grouping can still connect it to its own file and same-file siblings.
    Confirmed as a real bug (not fixed here) by measuring 77-81% attr-less nodes on
    cognirepo_test_repo/advanced/{moby,kubernetes}."""

    def test_below_threshold_symbol_still_gets_minimal_node(self, fresh_indexer, tmp_path, monkeypatch):
        from intelligence.indexer.ast_indexer import _LITE_GRAPH_WEIGHT_MIN
        from data.graph.graph_utils import make_node_id

        monkeypatch.chdir(tmp_path)
        fresh_indexer._graph_weight_min = _LITE_GRAPH_WEIGHT_MIN  # simulate large-repo lite-graph mode
        path = _write(tmp_path, "low_weight.py", "def a():\n    pass\n")
        fresh_indexer.index_file("low_weight.py", str(path), weight=_LITE_GRAPH_WEIGHT_MIN - 0.1)

        sym_node = make_node_id("FUNCTION", "a", file="low_weight.py")
        assert fresh_indexer.graph.node_exists(sym_node)
        attrs = fresh_indexer.graph.G.nodes[sym_node]
        assert attrs.get("type") == "FUNCTION"
        assert attrs.get("file") == "low_weight.py"
        # Rich attrs stay gated — this is still lite-graph mode, no regression on memory savings.
        assert "weight" not in attrs

        file_node = make_node_id("FILE", "low_weight.py")
        edge = fresh_indexer.graph.G.get_edge_data(sym_node, file_node)
        assert edge is not None and edge.get("rel") == "DEFINED_IN"

    def test_below_threshold_same_file_symbols_group_together(self, fresh_indexer, tmp_path, monkeypatch):
        """End-to-end AC1 check: two low-weight symbols in the same file must land in the
        same independence group (intelligence/retrieval/hybrid.py's component_id) — this was
        the exact bug (they got different groups because neither had a DEFINED_IN edge)."""
        from intelligence.indexer.ast_indexer import _LITE_GRAPH_WEIGHT_MIN
        from data.graph.graph_utils import make_node_id
        from intelligence.retrieval import hybrid as hybrid_mod
        from intelligence.retrieval.hybrid import HybridRetriever

        # Deterministic: bypass the (shared, TTL-cached) integrity gate entirely rather than
        # depend on its state — this test is about grouping correctness, not the gate itself.
        monkeypatch.setattr(hybrid_mod, "_grouping_allowed", lambda graph: True)

        monkeypatch.chdir(tmp_path)
        fresh_indexer._graph_weight_min = _LITE_GRAPH_WEIGHT_MIN
        path = _write(tmp_path, "shared.py", "def a():\n    pass\n\n\ndef b():\n    pass\n")
        low_weight = _LITE_GRAPH_WEIGHT_MIN - 0.1
        fresh_indexer.index_file("shared.py", str(path), weight=low_weight)

        n_a = make_node_id("FUNCTION", "a", file="shared.py")
        n_b = make_node_id("FUNCTION", "b", file="shared.py")
        r = HybridRetriever.__new__(HybridRetriever)
        r.graph = fresh_indexer.graph
        top = [
            {"_symbol": n_a, "text": "x", "final_score": 0.9, "source": "ast"},
            {"_symbol": n_b, "text": "x", "final_score": 0.8, "source": "ast"},
        ]
        grouped = r._annotate_independence_groups(top)
        assert grouped[0]["component_id"] == grouped[1]["component_id"]
