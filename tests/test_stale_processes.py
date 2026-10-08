# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""Stale cognirepo processes are noticed and stop on their own (COGNIREPO-119).

80 `python -m interface.cli.main init` processes (~40 MB each) were found alive for days. They were
watchers forked by `init` (a fork keeps its parent's argv) whose repo — a temp dir of a test run — had
been deleted. Nothing noticed the repo was gone, and the test suite kept creating more.
"""
import os
import shutil
import subprocess
import sys
import time

import pytest

from interface.cli import proc_scan
from interface.cli.proc_scan import CogniProc, find_stale

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="/proc is Linux-only")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _proc(command="init", age=10.0, deleted=False, pid=1234):
    return CogniProc(pid=pid, ppid=1, age_secs=age, rss_mb=40.0, command=command,
                     cwd="/tmp/gone", cwd_deleted=deleted)


class TestFindStale:
    def test_deleted_directory_is_stale(self):
        [(p, why)] = find_stale([_proc(deleted=True)])
        assert "directory was deleted" in why and p.pid == 1234

    def test_long_running_one_shot_command_is_stale(self):
        [(_p, why)] = find_stale([_proc("index-repo", age=7 * 3600)])
        assert "7 h" in why

    def test_young_one_shot_and_live_watcher_are_fine(self):
        assert find_stale([_proc("index-repo", age=600), _proc("watch", age=10 * 86400)]) == []

    def test_a_serve_session_is_never_reported(self):
        assert find_stale([_proc("serve", age=10 * 86400, deleted=True)]) == []

    def test_describe_lists_pids_and_total_memory(self):
        msg, hint = proc_scan.describe(find_stale([_proc(deleted=True, pid=11), _proc(deleted=True, pid=12)]))
        assert "2 stale" in msg and "80 MB" in msg and hint == "Stop them: kill 11 12"


class TestScan:
    def test_finds_a_real_process_whose_directory_was_deleted(self, real_process_scan, tmp_path):
        d = tmp_path / "repo"
        d.mkdir()
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)",  # pylint: disable=consider-using-with
                              "interface.cli.main", "init"], cwd=d)
        try:
            shutil.rmtree(d)
            deadline = time.time() + 10
            found = []
            while time.time() < deadline and not found:
                found = [x for x in proc_scan.scan() if x.pid == p.pid]
                time.sleep(0.05)
            assert found, "scan() did not see the process"
            assert found[0].command == "init" and found[0].cwd_deleted and found[0].rss_mb > 0
            assert [pp.pid for pp, _ in find_stale(found)] == [p.pid]
        finally:
            p.kill()
            p.wait(timeout=10)

    def test_ignores_unrelated_processes_and_itself(self, real_process_scan):
        pids = {x.pid for x in proc_scan.scan()}
        assert os.getpid() not in pids


def test_doctor_warns_about_stale_processes(isolated_cognirepo, monkeypatch, capsys):
    from interface.cli.main import _cmd_doctor
    monkeypatch.setattr(proc_scan, "scan", lambda *_a, **_k: [_proc(deleted=True, pid=4242)])
    _cmd_doctor(verbose=False)
    out = capsys.readouterr().out
    assert "stale cognirepo process" in out and "kill 4242" in out


_WATCHER = """
import os, sys
sys.path.insert(0, {repo!r})
from interface.cli import daemon
daemon._DIR_CHECK_EVERY = 1
WP = {wp!r}
class Obs:
    def is_alive(self): return True
def make():
    open(os.path.join({marks!r}, "started"), "w").close()
    return Obs()
def stop(_o):
    open(os.path.join({marks!r}, "stopped"), "w").close()
print("ready", flush=True)
daemon.run_watcher_with_crash_guard(make, stop, WP, "s", 0.1)
"""


@pytest.mark.timeout(60)
def test_watcher_stops_by_itself_when_its_directory_is_deleted(isolated_cognirepo, tmp_path):
    wp, marks = tmp_path / "repo", tmp_path / "marks"
    (wp / ".cognirepo" / "watchers").mkdir(parents=True)
    marks.mkdir()
    env = dict(os.environ, COGNIREPO_DIR=str(wp / ".cognirepo"))
    p = subprocess.Popen([sys.executable, "-c", _WATCHER.format(repo=_REPO, wp=str(wp), marks=str(marks))],  # pylint: disable=consider-using-with
                         env=env, cwd=str(tmp_path), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "ready"
        for _ in range(200):
            if (marks / "started").exists():
                break
            time.sleep(0.05)
        assert (marks / "started").exists()
        time.sleep(1.5)
        assert p.poll() is None, "still watching a live directory"
        shutil.rmtree(wp)
        assert p.wait(timeout=30) == 0
        assert (marks / "stopped").exists(), "the observer must be stopped cleanly (final flush)"
        assert "no longer exists" in p.stderr.read()
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=10)
