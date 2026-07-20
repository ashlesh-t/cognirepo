# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""
Tests for scripts/check_circular_deps.py — the layer-invariant checker introduced/
hardened by COGNIREPO-105 (both toplevel AND lazy upward imports are hard failures now).
"""
import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def _load_check_module():
    spec = importlib.util.spec_from_file_location(
        "check_circular_deps", REPO_ROOT / "scripts" / "check_circular_deps.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_graph(tmp_path, files: dict) -> str:
    graph = {"files": files, "reverse_deps": {}}
    out = tmp_path / "import-graph.json"
    out.write_text(json.dumps(graph), encoding="utf-8")
    return str(out)


class TestCheckCircularDeps:
    def test_passes_with_no_upward_imports(self, tmp_path, capsys):
        mod = _load_check_module()
        files = {
            "intelligence/orchestrator/router.py": {
                "internal_imports": [
                    {"from": "data.graph.knowledge_graph", "names": ["KnowledgeGraph"],
                     "lineno": 5, "kind": "toplevel"},
                ],
            },
        }
        graph_path = _write_graph(tmp_path, files)
        assert mod.check(graph_path, verbose=False) is True

    def test_fails_on_toplevel_upward_import(self, tmp_path):
        mod = _load_check_module()
        files = {
            "data/graph/behaviour_tracker.py": {
                "internal_imports": [
                    {"from": "intelligence.indexer.ast_indexer", "names": ["ASTIndexer"],
                     "lineno": 12, "kind": "toplevel"},
                ],
            },
        }
        graph_path = _write_graph(tmp_path, files)
        assert mod.check(graph_path, verbose=False) is False

    def test_fails_on_deliberately_added_lazy_upward_import(self, tmp_path):
        """AC2: a lazy (function-body) upward import is a hard failure, not just logged."""
        mod = _load_check_module()
        files = {
            "core/vector_db/local_vector_db.py": {
                "internal_imports": [
                    {"from": "data.memory.circuit_breaker", "names": ["get_breaker"],
                     "lineno": 167, "kind": "lazy"},
                ],
            },
        }
        graph_path = _write_graph(tmp_path, files)
        assert mod.check(graph_path, verbose=False) is False

    def test_type_checking_upward_import_does_not_fail(self, tmp_path):
        mod = _load_check_module()
        files = {
            "data/graph/behaviour_tracker.py": {
                "internal_imports": [
                    {"from": "intelligence.indexer.ast_indexer", "names": ["ASTIndexer"],
                     "lineno": 20, "kind": "type_check"},
                ],
            },
        }
        graph_path = _write_graph(tmp_path, files)
        assert mod.check(graph_path, verbose=False) is True

    def test_interface_cli_classified_as_cli_layer_not_interface(self, tmp_path):
        """interface/cli/*.py is layer 'cli' (5), above 'ops' (4) — calling into ops.cron
        is a legal downward import, not an upward interface→ops violation."""
        mod = _load_check_module()
        assert mod._pkg_of_file("interface/cli/main.py") == "cli"
        files = {
            "interface/cli/main.py": {
                "internal_imports": [
                    {"from": "ops.cron.prune_memory", "names": ["prune"],
                     "lineno": 3812, "kind": "lazy"},
                ],
            },
        }
        graph_path = _write_graph(tmp_path, files)
        assert mod.check(graph_path, verbose=False) is True

    def test_head_import_graph_has_only_known_deferred_violations(self):
        """Guards against silent regression of build_import_graph.py's INTERNAL_PACKAGES
        (COGNIREPO-105 fixed a stale set that made this check always trivially pass).
        COGNIREPO-D06 resolved the two core/vector_db/local_vector_db.py core→data
        violations that were deferred here — HEAD must now have zero layer violations."""
        mod = _load_check_module()
        graph_path = REPO_ROOT / "restructure" / "import-graph.json"
        if not graph_path.exists():
            import pytest
            pytest.skip("restructure/import-graph.json not built — run build_import_graph.py first")

        with open(graph_path, encoding="utf-8") as f:
            graph = json.load(f)

        violations = []
        for filepath, info in graph["files"].items():
            src_pkg = mod._pkg_of_file(filepath)
            src_layer = mod.LAYER_MAP.get(src_pkg)
            if src_layer is None:
                continue
            for imp in info.get("internal_imports", []):
                if imp.get("kind") == "type_check":
                    continue
                dep_pkg = mod._pkg_of_module(imp.get("from") or imp.get("module", ""))
                dep_layer = mod.LAYER_MAP.get(dep_pkg)
                if dep_layer is None or dep_layer <= src_layer:
                    continue
                violations.append(f"{filepath}:{imp.get('lineno')}")

        assert not violations, f"Unexpected layer violations at HEAD: {violations}"
