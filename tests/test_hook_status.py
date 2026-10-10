# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Post-commit hook records its outcome instead of discarding it (COGNIREPO-123)."""
import os
import subprocess
import time

import pytest

from interface.cli import hook_status as hs
from interface.cli.main import _hook_block


def _git(repo, *args, env=None):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / ".cognirepo").mkdir(parents=True)
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "a@a")
    _git(r, "config", "user.name", "n")
    hook = r / ".git" / "hooks" / "post-commit"
    hook.write_text("#!/bin/sh\n" + _hook_block())
    hook.chmod(0o755)
    return r


def _commit(repo, stub_body, name="f.py"):
    bindir = repo.parent / "bin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / "cognirepo"
    stub.write_text("#!/bin/sh\n" + stub_body + "\n")
    stub.chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
    (repo / name).write_text("def f(): pass\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "c", env=env)
    last = repo / ".cognirepo" / "hook.last"
    for _ in range(100):                                  # hook runs in the background
        if last.exists() and "files=" in last.read_text():
            break
        time.sleep(0.05)
    return last


def test_hook_is_valid_sh_and_no_longer_discards_stderr():
    block = _hook_block()
    assert "2>/dev/null &" not in block
    assert "hook.log" in block and "hook.last" in block and "--root" in block


def test_success_is_recorded(repo):
    last = _commit(repo, 'echo ok; exit 0')
    run = hs.read_last_run(str(repo / ".cognirepo"))
    assert run.ok and run.files == 1 and last.exists()


def test_failure_is_recorded_with_reason(repo):
    _commit(repo, 'echo "ImportError: Encryption requires additional packages." >&2; exit 3')
    run = hs.read_last_run(str(repo / ".cognirepo"))
    assert not run.ok and run.exit_code == 3
    assert "ImportError: Encryption requires" in run.reason
    assert "FAILED" in run.describe()


def test_command_not_found_is_recorded(repo):
    (repo / "f.py").write_text("x=1\n")
    _git(repo, "add", "-A")
    env = {**os.environ, "PATH": "/usr/bin:/bin"}
    _git(repo, "commit", "-qm", "c", env=env)
    last = repo / ".cognirepo" / "hook.last"
    for _ in range(100):
        if last.exists() and "files=" in last.read_text():
            break
        time.sleep(0.05)
    run = hs.read_last_run(str(repo / ".cognirepo"))
    assert run.exit_code == 127 and "not found" in run.reason


def test_log_rotates(repo):
    log = repo / ".cognirepo" / "hook.log"
    log.write_text("x" * 300_000)
    _commit(repo, "exit 0")
    assert (repo / ".cognirepo" / "hook.log.1").exists()
    assert log.stat().st_size < 1000


def test_reader_tolerates_missing_and_garbled(tmp_path):
    assert hs.read_last_run(str(tmp_path), None) is None
    (tmp_path / "hook.last").write_text("garbage")
    assert hs.read_last_run(str(tmp_path)) is None


def test_newest_hook_last_wins(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    (a / "hook.last").write_text("ts=t1\nexit=1\nfiles=1\n")
    (b / "hook.last").write_text("ts=t2\nexit=0\nfiles=2\n")
    os.utime(a / "hook.last", (1, 1))
    assert hs.read_last_run(str(a), str(b)).ts == "t2"


def test_outdated_block_detection():
    start = "# >>> cognirepo-hook-start <<<"
    cur = _hook_block()
    assert not hs.hook_is_outdated("#!/bin/sh\n" + cur, cur, start)
    assert hs.hook_is_outdated(f"{start}\nold 2>/dev/null &\n", cur, start)
    assert not hs.hook_is_outdated("#!/bin/sh\necho mine\n", cur, start)


def test_session_brief_flags_failed_hook(tmp_path, monkeypatch):
    monkeypatch.setattr("core.config.paths.get_cognirepo_dir", lambda: str(tmp_path))
    (tmp_path / "hook.last").write_text("ts=t\nexit=1\nfiles=2\n")
    (tmp_path / "hook.log").write_text("--- 2026-01-01T00:00:00Z x\nboom\nexit=1\n")
    from interface.tools.prime_session import _detect_blind_spots
    spots = _detect_blind_spots({})
    assert any("Post-commit hook" in s and "boom" in s for s in spots)
