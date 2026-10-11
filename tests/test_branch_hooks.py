# pylint: disable=missing-docstring, import-outside-toplevel, redefined-outer-name
# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""post-checkout / post-merge / post-rewrite hooks keep the index in step after a branch change.

Runs the generated hook scripts in a real git repo with a ``cognirepo`` shim on PATH that records
its arguments, so what is asserted is exactly which files the hook hands to ``index-repo``.
"""
from __future__ import annotations

import os
import stat
import subprocess
import time

import pytest


def _git(repo, *args, check=True):
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
        cwd=repo, check=check, capture_output=True, text=True,
    )


def _calls(repo):
    """The shim's record file (a sibling of the repo)."""
    return repo.parent / "calls.txt"


def _commit(repo, name, text="x = 1\n"):
    (repo / name).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"add {name}")


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    calls = tmp_path / "calls.txt"
    shim = shim_dir / "cognirepo"
    shim.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\n')
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    (r / ".git" / "info" / "exclude").write_text(".cognirepo/\n")   # as the real .gitignore does
    _commit(r, "base.py")
    (r / ".cognirepo").mkdir()
    monkeypatch.chdir(r)
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ['PATH']}")
    from interface.cli.main import _cmd_install_hooks
    assert _cmd_install_hooks() == 0
    time.sleep(0.2)
    calls.write_text("")
    return r


def _wait_calls(repo, want_empty=False, timeout=5.0):
    """The hook backgrounds its work; poll for the shim's record."""
    end = time.time() + timeout
    while time.time() < end:
        text = _calls(repo).read_text().strip()
        if text and not want_empty:
            return text
        time.sleep(0.05)
    return _calls(repo).read_text().strip()


def test_installs_all_four_hooks_and_is_idempotent(repo):
    from interface.cli.main import _HOOK_EVENTS, _cmd_install_hooks, _hook_block
    hooks = repo / ".git" / "hooks"
    for ev in _HOOK_EVENTS:
        text = (hooks / ev).read_text()
        assert _hook_block(ev) in text and os.access(hooks / ev, os.X_OK)
    before = {ev: (hooks / ev).read_text() for ev in _HOOK_EVENTS}
    assert _cmd_install_hooks() == 0
    assert {ev: (hooks / ev).read_text() for ev in _HOOK_EVENTS} == before


def test_checkout_branch_reindexes_files_that_differ(repo):
    _git(repo, "checkout", "-qb", "feat")
    _commit(repo, "feat_only.py")
    _git(repo, "checkout", "-q", "main")
    out = _wait_calls(repo)
    assert "--files" in out and "feat_only.py" in out and "base.py" not in out


def test_checkout_passes_deleted_files_too(repo):
    _git(repo, "checkout", "-qb", "feat")
    (repo / "base.py").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "rm base")
    _calls(repo).write_text("")
    _git(repo, "checkout", "-q", "main")
    assert "base.py" in _wait_calls(repo)       # a path gone on the other branch: #169 tombstones it


def test_file_checkout_and_noop_switch_do_nothing(repo):
    (repo / "base.py").write_text("x = 2\n")
    _git(repo, "checkout", "--", "base.py")      # $3 = 0: a file checkout, not a branch switch
    _git(repo, "checkout", "-q", "main")         # same commit
    assert _wait_calls(repo, want_empty=True, timeout=1.0) == ""


def test_merge_reindexes_what_the_merge_brought_in(repo):
    _git(repo, "checkout", "-qb", "feat")
    _commit(repo, "merged_in.py")
    _git(repo, "checkout", "-q", "main")
    _calls(repo).write_text("")
    _git(repo, "merge", "-q", "--ff-only", "feat")
    out = _wait_calls(repo)
    assert "merged_in.py" in out


def test_rebase_reindexes_but_amend_does_not_double_fire(repo):
    _git(repo, "checkout", "-qb", "feat")
    _commit(repo, "f1.py")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "m1.py")
    _git(repo, "checkout", "-q", "feat")
    _calls(repo).write_text("")
    _git(repo, "rebase", "-q", "main")
    assert "m1.py" in _wait_calls(repo)
    _calls(repo).write_text("")
    _git(repo, "commit", "-q", "--amend", "--no-edit")
    time.sleep(0.5)
    out = _calls(repo).read_text()
    assert out.count("--files") <= 1             # post-commit only; post-rewrite ignores amend


def test_huge_change_runs_a_full_reindex_instead_of_a_giant_argv(repo, monkeypatch):
    import interface.cli.main as cli
    monkeypatch.setattr(cli, "_HOOK_FULL_REINDEX_FILES", 3)
    assert cli._cmd_install_hooks() == 0
    _git(repo, "checkout", "-qb", "feat")
    for i in range(5):
        (repo / f"f{i}.py").write_text("x = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "many")
    _calls(repo).write_text("")
    _git(repo, "checkout", "-q", "main")
    out = _wait_calls(repo)
    assert out.startswith("index-repo .") and "--files" not in out


def test_user_commands_after_our_block_still_run(repo):
    hook = repo / ".git" / "hooks" / "post-checkout"
    marker = repo / "ran_after.txt"
    hook.write_text(hook.read_text() + f"\ntouch {marker}\n")
    _git(repo, "checkout", "-qb", "feat")        # $1 == $2: our block does nothing, rest must run
    assert marker.exists()


def test_uninstall_removes_every_block_and_keeps_user_lines(repo):
    from interface.cli.main import _HOOK_EVENTS, _HOOK_SENTINEL_START, _cmd_uninstall_hooks
    hooks = repo / ".git" / "hooks"
    (hooks / "post-merge").write_text((hooks / "post-merge").read_text() + "\necho mine\n")
    assert _cmd_uninstall_hooks() == 0
    for ev in _HOOK_EVENTS:
        if ev == "post-merge":
            text = (hooks / ev).read_text()
            assert "echo mine" in text and _HOOK_SENTINEL_START not in text
        else:
            assert not (hooks / ev).exists()
