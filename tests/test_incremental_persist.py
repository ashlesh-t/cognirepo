# pylint: disable=missing-docstring, import-outside-toplevel, too-few-public-methods, protected-access
# pylint: disable=redefined-outer-name, unused-argument
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_incremental_persist.py — COGNIREPO-154 / COGNIREPO-155.

`index-repo --files` (the post-commit hook) and `--changed-only` must persist the AST
index (+ FAISS + manifest), not just the graph; the hook and `--changed-only` must take
their extension lists from `language_registry`; and `--changed-only` must fail honestly
when git is unavailable.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_cli(monkeypatch, *argv):
    from interface.cli import main as cli
    monkeypatch.setattr(sys, "argv", ["cognirepo", *argv])
    cli._main()


def _git(*args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   check=True, capture_output=True)


@pytest.fixture()
def no_model(monkeypatch):
    """Fail loudly if anything tries to load the embedding model."""
    from intelligence.indexer import ast_indexer

    def _boom(*_a, **_k):
        raise AssertionError("embedding model must not be loaded with --no-embed")
    monkeypatch.setattr(ast_indexer, "get_model", _boom)


@pytest.fixture()
def indexed_repo(isolated_cognirepo, tmp_path, no_model):
    """A repo with a complete full index (graph marked complete + AST index on disk)."""
    from data.graph.knowledge_graph import KnowledgeGraph
    from intelligence.indexer.ast_indexer import ASTIndexer
    (tmp_path / "a.py").write_text("def existing():\n    return 1\n")
    (tmp_path / "b.py").write_text("from a import existing\n\ndef caller():\n    return existing()\n")
    kg = KnowledgeGraph()
    indexer = ASTIndexer(graph=kg)
    indexer.index_repo(str(tmp_path), embed=False)
    indexer.save()
    kg.save()
    return tmp_path


def _fresh_process_lookup(tmp_path, name: str) -> list:
    """lookup_symbol against what is on disk, from a separate interpreter."""
    code = (
        "import json, sys\n"
        "from data.graph.knowledge_graph import KnowledgeGraph\n"
        "from intelligence.indexer.ast_indexer import ASTIndexer\n"
        "idx = ASTIndexer(graph=KnowledgeGraph()); idx.load()\n"
        f"print(json.dumps(idx.lookup_symbol({name!r})))\n"
    )
    env = {**os.environ, "COGNIREPO_DIR": str(tmp_path / ".cognirepo"),
           "PYTHONPATH": _REPO_ROOT}
    out = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env,
                         check=True, capture_output=True, text=True).stdout
    return json.loads(out.strip().splitlines()[-1])


class TestFilesPersistsAstIndex:
    def test_new_symbol_visible_to_a_fresh_process(self, indexed_repo, monkeypatch):
        (indexed_repo / "hookfile.py").write_text("def only_via_hook():\n    return 42\n")
        _run_cli(monkeypatch, "index-repo", "--files", "hookfile.py", "--no-watch", "--no-embed")
        ast_index = (indexed_repo / ".cognirepo" / "index" / "ast_index.json").read_text()
        assert "hookfile.py" in ast_index
        locs = _fresh_process_lookup(indexed_repo, "only_via_hook")
        assert [loc["file"] for loc in locs] == ["hookfile.py"]

    def test_existing_index_is_kept_not_replaced(self, indexed_repo, monkeypatch):
        """save() must write the loaded full index plus the new file, not just the new file."""
        (indexed_repo / "hookfile.py").write_text("def only_via_hook():\n    return 42\n")
        _run_cli(monkeypatch, "index-repo", "--files", "hookfile.py", "--no-embed")
        data = json.loads((indexed_repo / ".cognirepo" / "index" / "ast_index.json").read_text())
        assert {"a.py", "b.py", "hookfile.py"} <= set(data["files"])
        assert data["total_symbols"] == sum(len(f["symbols"]) for f in data["files"].values())
        assert "existing" in data["reverse_index"] and "only_via_hook" in data["reverse_index"]

    def test_edited_symbol_rename_drops_old_name(self, indexed_repo, monkeypatch):
        (indexed_repo / "a.py").write_text("def renamed():\n    return 1\n")
        _run_cli(monkeypatch, "index-repo", "--files", "a.py", "--no-embed")
        assert _fresh_process_lookup(indexed_repo, "existing") == []
        assert [loc["file"] for loc in _fresh_process_lookup(indexed_repo, "renamed")] == ["a.py"]

    def test_manifest_written(self, indexed_repo, monkeypatch):
        (indexed_repo / "hookfile.py").write_text("def only_via_hook():\n    return 42\n")
        _run_cli(monkeypatch, "index-repo", "--files", "hookfile.py", "--no-embed")
        manifest = json.loads((indexed_repo / ".cognirepo" / "index" / "manifest.json").read_text())
        assert manifest["source_file_count"] == 3       # a.py, b.py + the hook-indexed file

    def test_guard_still_runs_first_and_writes_nothing(
            self, isolated_cognirepo, tmp_path, monkeypatch, capsys):
        """COGNIREPO-122 unchanged: no base graph → exit 2, no AST index written."""
        (tmp_path / "new.py").write_text("def brand_new():\n    return 1\n")
        with pytest.raises(SystemExit) as exc:
            _run_cli(monkeypatch, "index-repo", "--files", "new.py", "--no-embed")
        assert exc.value.code == 2
        assert not (tmp_path / ".cognirepo" / "index" / "ast_index.json").exists()
        assert "not updating the graph" in capsys.readouterr().err


class TestChangedOnly:
    def _git_repo(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        _git("add", "a.py", "b.py")
        _git("commit", "-qm", "init")

    def test_changed_only_persists_ast_index(self, indexed_repo, monkeypatch):
        self._git_repo(indexed_repo)
        (indexed_repo / "fresh.py").write_text("def from_changed_only():\n    return 1\n")
        _run_cli(monkeypatch, "index-repo", "--changed-only", "--no-embed")
        locs = _fresh_process_lookup(indexed_repo, "from_changed_only")
        assert [loc["file"] for loc in locs] == ["fresh.py"]

    def test_extension_set_comes_from_language_registry(self, indexed_repo, monkeypatch, capsys):
        self._git_repo(indexed_repo)
        (indexed_repo / "fresh.py").write_text("def p():\n    return 1\n")
        (indexed_repo / "fresh.go").write_text("package m\nfunc G() {}\n")
        from intelligence.indexer import language_registry
        monkeypatch.setattr(language_registry, "supported_extensions", lambda: [".py"])
        _run_cli(monkeypatch, "index-repo", "--changed-only", "--no-embed")
        out = capsys.readouterr().out
        assert "Re-indexed 1 changed file(s): fresh.py" in out

    def test_no_git_fails_honestly(self, isolated_cognirepo, tmp_path, monkeypatch, capsys):
        """COGNIREPO-155: no fake 'fallback', non-zero exit, no last-indexed sha, lock removed."""
        lock = tmp_path / "idx.lock"
        lock.write_text("")
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
        with pytest.raises(SystemExit) as exc:
            _run_cli(monkeypatch, "index-repo", "--changed-only", "--remove-lock", str(lock))
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "Nothing was indexed" in err and "falling back" not in err
        assert not (tmp_path / ".cognirepo" / "index" / "last_indexed.json").exists()
        assert not lock.exists()


class TestHookExtensions:
    def _regex(self, block: str) -> str:
        line = next(l for l in block.splitlines() if "grep -E" in l)
        return line.split("grep -E '", 1)[1].rsplit("'", 1)[0]

    def test_hook_regex_matches_language_registry(self):
        import re
        from interface.cli.main import _hook_block
        from intelligence.indexer.language_registry import known_extensions
        m = re.fullmatch(r"\\\.\((.*)\)\$", self._regex(_hook_block()))
        assert m is not None
        assert {"." + e for e in m.group(1).split("|")} == set(known_extensions())

    def test_hook_grep_selects_registry_extensions_only(self):
        from interface.cli.main import _hook_block
        from intelligence.indexer.language_registry import known_extensions
        names = [f"src/x{ext}" for ext in known_extensions()] + ["README.md", "notes.txt"]
        res = subprocess.run(["grep", "-E", self._regex(_hook_block())],
                             input="\n".join(names) + "\n", capture_output=True, text=True,
                             check=False)
        assert res.stdout.split() == names[:-2]

    def test_hook_skips_embedding(self):
        from interface.cli.main import _hook_block
        assert "--files $changed --no-watch --no-embed" in _hook_block()

    def test_install_hooks_replaces_a_stale_block(self, tmp_path, monkeypatch):
        from interface.cli.main import (
            _HOOK_SENTINEL_END, _HOOK_SENTINEL_START, _cmd_install_hooks, _hook_block,
        )
        monkeypatch.chdir(tmp_path)
        hooks = tmp_path / ".git" / "hooks"
        hooks.mkdir(parents=True)
        stale = (f"{_HOOK_SENTINEL_START}\nchanged=$(git diff-tree … | grep -E '\\.(py|js)$')\n"
                 f"{_HOOK_SENTINEL_END}\n")
        (hooks / "post-commit").write_text("#!/bin/sh\necho mine\n\n" + stale)
        assert _cmd_install_hooks() == 0
        content = (hooks / "post-commit").read_text()
        assert "echo mine" in content                      # user's own hook lines kept
        assert _hook_block() in content
        assert "(py|js)" not in content
        assert content.count(_HOOK_SENTINEL_START) == 1
        assert _cmd_install_hooks() == 0                   # idempotent
        assert (hooks / "post-commit").read_text() == content
