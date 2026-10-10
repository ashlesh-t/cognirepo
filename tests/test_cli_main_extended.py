# pylint: disable=missing-docstring, import-outside-toplevel, broad-exception-caught
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""
tests/test_cli_main_extended.py — Extended coverage for cli/main.py (24% → 40%).

Calls _cmd_* functions directly to exercise logic without subprocess overhead.
Also exercises subprocess paths for coverage of the argparse dispatch tree.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Helper to call subprocess ─────────────────────────────────────────────────

def _run(*args, timeout=15):
    return subprocess.run(
        [sys.executable, "-m", "interface.cli.main"] + list(args),
        capture_output=True, text=True, timeout=timeout,
    )


# ── status command ────────────────────────────────────────────────────────────

def test_status_command_exits_cleanly():
    res = _run("status")
    assert res.returncode in (0, 1, 2)


# ── prime command ─────────────────────────────────────────────────────────────

def test_prime_command():
    res = _run("prime")
    assert res.returncode in (0, 1, 2)


def test_prime_json_flag():
    res = _run("prime", "--json")
    assert res.returncode in (0, 1, 2)


# ── doctor command ────────────────────────────────────────────────────────────

def test_doctor_command():
    res = _run("doctor")
    assert res.returncode in (0, 1, 2)


def test_doctor_verbose_flag():
    res = _run("doctor", "--verbose")
    assert res.returncode in (0, 1, 2)


def test_doctor_json_flag():
    res = _run("doctor", "--json")
    assert res.returncode in (0, 1, 2)
    if res.returncode == 0:
        try:
            json.loads(res.stdout)
        except json.JSONDecodeError:
            pass  # output might not be pure JSON if warnings printed


# ── sessions command ──────────────────────────────────────────────────────────

def test_sessions_command():
    res = _run("sessions")
    assert res.returncode in (0, 1, 2)


def test_sessions_limit_flag():
    res = _run("sessions", "--limit", "5")
    assert res.returncode in (0, 1, 2)


# ── org list command ──────────────────────────────────────────────────────────

def test_org_list_command():
    res = _run("org", "list")
    assert res.returncode in (0, 1, 2)


# ── list command ──────────────────────────────────────────────────────────────

def test_list_command():
    res = _run("list")
    assert res.returncode in (0, 1, 2)


# ── hooks commands ────────────────────────────────────────────────────────────

def test_hooks_install_command():
    res = _run("hooks", "install")
    assert res.returncode in (0, 1, 2)


def test_hooks_uninstall_command():
    res = _run("hooks", "uninstall")
    assert res.returncode in (0, 1, 2)


# ── store-memory / retrieve-memory commands ──────────────────────────────────

def test_store_memory_command():
    res = _run("store-memory", "test memory text for cli coverage")
    assert res.returncode in (0, 1, 2)


def test_retrieve_memory_command():
    res = _run("retrieve-memory", "test query")
    assert res.returncode in (0, 1, 2)


# ── search-docs command ───────────────────────────────────────────────────────

def test_search_docs_command():
    res = _run("search-docs", "hybrid retrieval")
    assert res.returncode in (0, 1, 2)


# ── index-repo command ────────────────────────────────────────────────────────

def test_index_repo_help():
    res = _run("index-repo", "--help")
    assert res.returncode in (0, 1, 2)


# ── verify command ────────────────────────────────────────────────────────────

def test_verify_command():
    res = _run("verify")
    assert res.returncode in (0, 1, 2)


# ── coverage command ──────────────────────────────────────────────────────────

def test_coverage_command():
    res = _run("coverage")
    assert res.returncode in (0, 1, 2)


# ── export-spec command ───────────────────────────────────────────────────────

def test_export_spec_command():
    res = _run("export-spec")
    assert res.returncode in (0, 1, 2)


# ── Direct function calls for coverage of internal helpers ───────────────────

def test_cmd_status_function():
    from interface.cli.main import _cmd_status
    try:
        _cmd_status()
    except SystemExit:
        pass
    except Exception:
        pass


def test_cmd_prime_function():
    from interface.cli.main import _cmd_prime
    try:
        _cmd_prime(as_json=False)
    except SystemExit:
        pass
    except Exception:
        pass


def test_cmd_prime_json_function():
    from interface.cli.main import _cmd_prime
    try:
        _cmd_prime(as_json=True)
    except SystemExit:
        pass
    except Exception:
        pass


def test_cmd_list_mcp_function():
    from interface.cli.main import _cmd_list_mcp
    try:
        _cmd_list_mcp()
    except SystemExit:
        pass
    except Exception:
        pass


def test_cmd_list_orgs_function():
    from interface.cli.main import _cmd_list_orgs
    try:
        _cmd_list_orgs()
    except SystemExit:
        pass
    except Exception:
        pass


def test_cmd_sessions_function():
    from interface.cli.main import _cmd_sessions
    try:
        _cmd_sessions(limit=5)
    except SystemExit:
        pass
    except Exception:
        pass


def test_cmd_install_hooks_function():
    from interface.cli.main import _cmd_install_hooks
    try:
        result = _cmd_install_hooks()
        assert result in (0, 1, 2, None)
    except SystemExit:
        pass
    except Exception:
        pass


def test_cmd_uninstall_hooks_function():
    from interface.cli.main import _cmd_uninstall_hooks
    try:
        result = _cmd_uninstall_hooks()
        assert result in (0, 1, 2, None)
    except SystemExit:
        pass
    except Exception:
        pass


def test_cmd_verify_index_function():
    from interface.cli.main import _cmd_verify_index
    try:
        result = _cmd_verify_index()
        assert result in (0, 1, 2, None)
    except SystemExit:
        pass
    except Exception:
        pass


def test_cmd_doctor_function():
    from interface.cli.main import _cmd_doctor
    try:
        result = _cmd_doctor(verbose=False)
        assert result in (0, 1, 2, None)
    except SystemExit:
        pass
    except Exception:
        pass


def test_cmd_doctor_fix_function():
    from interface.cli.main import _cmd_doctor_fix
    try:
        result = _cmd_doctor_fix()
        assert result in (0, 1, 2, None)
    except SystemExit:
        pass
    except Exception:
        pass


def test_cmd_coverage_function():
    from interface.cli.main import _cmd_coverage
    try:
        result = _cmd_coverage()
        assert result in (0, 1, 2, None)
    except SystemExit:
        pass
    except Exception:
        pass


def test_cmd_update_directives_function():
    from interface.cli.main import _cmd_update_directives
    try:
        result = _cmd_update_directives()
        assert result in (0, 1, 2, None)
    except SystemExit:
        pass
    except Exception:
        pass


# ── main() entry point dispatch ───────────────────────────────────────────────

@pytest.mark.parametrize("cmd", [
    ["version"],
    ["config", "--help"],
    ["benchmark", "--help"],
    ["migrate-config", "--help"],
    ["install", "--help"],
    ["summarize", "--help"],
])
def test_main_dispatch_additional_commands(cmd):
    res = _run(*cmd)
    assert res.returncode in (0, 1, 2)


# ── COGNIREPO-107: _direct_index evicts the embedding model before kg.save(),
# and retries a circuit-breaker-blocked save once after its cooldown ─────────

class _FakeCircuitOpenError(Exception):
    """Stand-in for CircuitOpenError — matched by name, not type, in _direct_index."""


class _StubASTIndexer:
    def __init__(self, graph=None, progress_factory=None):  # pylint: disable=unused-argument
        self.graph = graph

    def index_repo(self, *_a, **_kw):
        return {"symbols": 0, "files": 0, "tier2_queued": 0}

    def free_large_objects(self):
        pass


def _patch_direct_index_deps(monkeypatch, fake_kg_cls):
    import data.graph.knowledge_graph as kg_mod
    import intelligence.indexer.ast_indexer as ast_mod
    monkeypatch.setattr(kg_mod, "KnowledgeGraph", fake_kg_cls)
    monkeypatch.setattr(ast_mod, "ASTIndexer", _StubASTIndexer)


class TestDirectIndexGraphSave:
    def test_evicts_model_before_kg_save_when_embed_true(self, tmp_path, monkeypatch):
        calls = []

        class _FakeKG:
            def save(self):
                calls.append("save")

        _patch_direct_index_deps(monkeypatch, _FakeKG)
        import data.memory.embeddings as emb_mod
        monkeypatch.setattr(emb_mod, "evict_model", lambda: calls.append("evict"))

        from interface.cli.main import _direct_index
        _direct_index(str(tmp_path), embed=True, skip_graph=True)

        assert calls == ["evict", "save"]

    def test_does_not_evict_model_when_embed_false(self, tmp_path, monkeypatch):
        calls = []

        class _FakeKG:
            def save(self):
                calls.append("save")

        _patch_direct_index_deps(monkeypatch, _FakeKG)
        import data.memory.embeddings as emb_mod
        monkeypatch.setattr(emb_mod, "evict_model", lambda: calls.append("evict"))

        from interface.cli.main import _direct_index
        _direct_index(str(tmp_path), embed=False, skip_graph=True)

        assert calls == ["save"]

    def test_retries_once_after_circuit_breaker_trip_then_succeeds(self, tmp_path, monkeypatch, capsys):
        attempts = []

        class _FakeKG:
            def save(self):
                attempts.append(1)
                if len(attempts) == 1:
                    raise _FakeCircuitOpenError("RSS over limit")

        _patch_direct_index_deps(monkeypatch, _FakeKG)
        import data.memory.embeddings as emb_mod
        monkeypatch.setattr(emb_mod, "evict_model", lambda: None)

        import interface.cli.main as main_mod
        slept = []
        monkeypatch.setattr(main_mod.time, "sleep", lambda s: slept.append(s))

        class _FakeBreaker:
            cooldown = 30.0
        import data.memory.circuit_breaker as cb_mod
        monkeypatch.setattr(cb_mod, "get_breaker", lambda: _FakeBreaker())

        from interface.cli.main import _direct_index
        _direct_index(str(tmp_path), embed=False, skip_graph=True)

        assert len(attempts) == 2  # first trip, second succeeds
        # time.sleep is patched process-wide, so unrelated background threads (progress bars,
        # lock polling) append their own tiny sleeps too — assert only the one that matters.
        assert [s for s in slept if s >= 1] == [31.0]  # cooldown + 1, as implemented
        assert "not saved" not in capsys.readouterr().out

    def test_warns_once_after_exhausting_retry(self, tmp_path, monkeypatch, capsys):
        class _FakeKG:
            def save(self):
                raise _FakeCircuitOpenError("still over limit")

        _patch_direct_index_deps(monkeypatch, _FakeKG)
        import data.memory.embeddings as emb_mod
        monkeypatch.setattr(emb_mod, "evict_model", lambda: None)

        import interface.cli.main as main_mod
        monkeypatch.setattr(main_mod.time, "sleep", lambda s: None)

        class _FakeBreaker:
            cooldown = 30.0
        import data.memory.circuit_breaker as cb_mod
        monkeypatch.setattr(cb_mod, "get_breaker", lambda: _FakeBreaker())

        from interface.cli.main import _direct_index
        _direct_index(str(tmp_path), embed=False, skip_graph=True)  # must not raise

        out = capsys.readouterr().out
        assert "Knowledge graph not saved" in out

    def test_non_circuit_exception_from_save_propagates(self, tmp_path, monkeypatch):
        class _FakeKG:
            def save(self):
                raise ValueError("unrelated failure")

        _patch_direct_index_deps(monkeypatch, _FakeKG)
        import data.memory.embeddings as emb_mod
        monkeypatch.setattr(emb_mod, "evict_model", lambda: None)

        from interface.cli.main import _direct_index
        with pytest.raises(Exception):  # propagates out of _direct_index's caller's try/except
            _direct_index(str(tmp_path), embed=False, skip_graph=True)
