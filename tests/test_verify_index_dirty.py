# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""
tests/test_verify_index_dirty.py — COGNIREPO-104: verify-index working-tree
staleness detection.

Exercises _cmd_verify_index() against a real git repo (isolated_cognirepo fixture
chdirs into tmp_path) so `git status --porcelain` and mtime comparisons are real,
not mocked.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import time
from datetime import datetime, timezone

import faiss
import pytest


def _sh(*args):
    subprocess.run(["git", *args], check=True, capture_output=True)


def _init_git_repo():
    _sh("init", "-q")
    _sh("config", "user.email", "test@example.com")
    _sh("config", "user.name", "Test")


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def _write_manifest(indexed_at: str | None = None):
    """Write real index files + a manifest.json that verify-index will accept as OK."""
    from core.config.paths import get_path
    from intelligence.indexer.ast_indexer import (
        _ast_index_file, _ast_faiss_file, _ast_meta_file, _manifest_file,
    )

    os.makedirs(get_path("index"), exist_ok=True)
    for f in (_ast_index_file(), _ast_faiss_file(), _ast_meta_file()):
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("stub")

    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()

    manifest = {
        "platform": {"arch": platform.machine(), "faiss": faiss.__version__},
        "index_checksums": {
            "ast_index.json": _sha256(_ast_index_file()),
            "ast.index": _sha256(_ast_faiss_file()),
            "ast_metadata.json": _sha256(_ast_meta_file()),
        },
        "git_commit": git_commit,
        "indexed_at": indexed_at or datetime.now(tz=timezone.utc).isoformat(),
        "source_file_count": 1,
        "symbol_count": 1,
    }
    with open(_manifest_file(), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)
    return git_commit


class TestVerifyIndexDirtyDetection:
    def test_clean_tree_is_ok_exit_0(self):
        from interface.cli.main import _cmd_verify_index

        _init_git_repo()
        with open("mod.py", "w", encoding="utf-8") as f:
            f.write("def foo(): pass\n")
        _sh("add", "-A")
        _sh("commit", "-q", "-m", "init")

        _write_manifest()

        code = _cmd_verify_index()
        assert code == 0

    def test_dirty_indexed_py_file_flagged(self, capsys):
        from interface.cli.main import _cmd_verify_index

        _init_git_repo()
        with open("mod.py", "w", encoding="utf-8") as f:
            f.write("def foo(): pass\n")
        _sh("add", "-A")
        _sh("commit", "-q", "-m", "init")

        # index built "in the past" so the edit below is unambiguously newer
        _write_manifest(indexed_at=datetime.now(tz=timezone.utc).isoformat())
        time.sleep(2.5)  # clear the ±2s clock-skew tolerance window

        with open("mod.py", "a", encoding="utf-8") as f:
            f.write("def bar(): pass\n")

        code = _cmd_verify_index()
        out = capsys.readouterr().out

        assert code == 1
        assert "DIRTY" in out
        assert "mod.py" in out

    def test_dirty_non_indexed_extension_not_flagged(self, capsys):
        from interface.cli.main import _cmd_verify_index

        _init_git_repo()
        with open("mod.py", "w", encoding="utf-8") as f:
            f.write("def foo(): pass\n")
        with open("README.md", "w", encoding="utf-8") as f:
            f.write("# hi\n")
        _sh("add", "-A")
        _sh("commit", "-q", "-m", "init")

        _write_manifest()
        time.sleep(2.5)

        with open("README.md", "a", encoding="utf-8") as f:
            f.write("more docs\n")

        code = _cmd_verify_index()
        out = capsys.readouterr().out

        assert code == 0
        assert "DIRTY" not in out

    def test_non_git_directory_degrades_gracefully(self, capsys):
        from interface.cli.main import _cmd_verify_index

        # No `git init` — repo root is a plain directory.
        _write_manifest_no_git()

        code = _cmd_verify_index()
        out = capsys.readouterr().out

        assert code in (0, 1)  # must not raise
        assert "DIRTY" not in out

    def test_verbose_lists_more_than_five_dirty_files(self, capsys):
        from interface.cli.main import _cmd_verify_index

        _init_git_repo()
        for i in range(7):
            with open(f"mod{i}.py", "w", encoding="utf-8") as f:
                f.write("def foo(): pass\n")
        _sh("add", "-A")
        _sh("commit", "-q", "-m", "init")

        _write_manifest()
        time.sleep(2.5)

        for i in range(7):
            with open(f"mod{i}.py", "a", encoding="utf-8") as f:
                f.write("def bar(): pass\n")

        code = _cmd_verify_index(verbose=True)
        out = capsys.readouterr().out

        assert code == 1
        for i in range(7):
            assert f"mod{i}.py" in out


def _write_manifest_no_git():
    """Manifest with an unresolvable git_commit — mirrors a non-git working dir."""
    from core.config.paths import get_path
    from intelligence.indexer.ast_indexer import (
        _ast_index_file, _ast_faiss_file, _ast_meta_file, _manifest_file,
    )

    os.makedirs(get_path("index"), exist_ok=True)
    for f in (_ast_index_file(), _ast_faiss_file(), _ast_meta_file()):
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("stub")

    manifest = {
        "platform": {"arch": platform.machine(), "faiss": faiss.__version__},
        "index_checksums": {
            "ast_index.json": _sha256(_ast_index_file()),
            "ast.index": _sha256(_ast_faiss_file()),
            "ast_metadata.json": _sha256(_ast_meta_file()),
        },
        "git_commit": "unknown",
        "indexed_at": datetime.now(tz=timezone.utc).isoformat(),
        "source_file_count": 0,
        "symbol_count": 0,
    }
    with open(_manifest_file(), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)
