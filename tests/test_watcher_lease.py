# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""One watcher per repo, however many processes try to start one (COGNIREPO-138).

Before: every `cognirepo serve` (one per agent session) started its own unregistered watcher thread
and the per-pid flock excluded nothing, so N sessions meant N watchers each saving its own copy of
the graph/index. Now the process that runs the observer holds a per-repo lease (OS advisory lock,
released by the kernel on death) and is the only one to register / heartbeat.
"""
import json
import os
import signal
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"),
                                reason="daemon management is Linux-only")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A watcher process: tries to become THE watcher (optionally standing by), records that its
# observer started, then runs until killed. `MODE`: "guard" = take the lease inside the crash
# guard, "standby" = wait for the lease first (what `serve` does).
_WATCHER = """
import os, sys, time
sys.path.insert(0, {repo!r})
from interface.cli import daemon
WP = {wp!r}
marks = os.path.join(WP, "marks")
os.makedirs(marks, exist_ok=True)
class Obs:
    def is_alive(self): return True
def make():
    open(os.path.join(marks, "started.%d" % os.getpid()), "w").close()
    return Obs()
def stop(_o): pass
reg = {{"name": "w-%d" % os.getpid(), "log": "x", "kind": {kind!r}}}
print("ready", flush=True)
if {standby!r}:
    lease = daemon.wait_for_watcher_lease(WP, poll=0.1)
    ran = daemon.run_watcher_with_crash_guard(make, stop, WP, "s", 0.1, lease=lease, registration=reg)
else:
    ran = daemon.run_watcher_with_crash_guard(make, stop, WP, "s", 0.1, registration=reg)
open(os.path.join(marks, "refused.%d" % os.getpid()), "w").close() if not ran else None
"""


def _spawn(tmp_path, *, standby=False, kind=None):
    env = dict(os.environ, COGNIREPO_DIR=os.path.join(str(tmp_path), ".cognirepo"))
    os.makedirs(os.path.join(str(tmp_path), ".cognirepo", "watchers"), exist_ok=True)
    code = _WATCHER.format(repo=_REPO, wp=str(tmp_path), standby=standby, kind=kind)
    p = subprocess.Popen([sys.executable, "-c", code, "cognirepo-test-watcher"], env=env,  # pylint: disable=consider-using-with
                         cwd=str(tmp_path), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "ready", p.stderr.read()
    return p


def _marks(tmp_path, prefix):
    d = tmp_path / "marks"
    return sorted(int(n.split(".")[1]) for n in os.listdir(d) if n.startswith(prefix + ".")) if d.exists() else []


def _wait(cond, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _reap(*procs):
    for p in procs:
        if p.poll() is None:
            p.kill()
        p.wait(timeout=10)


def _registry(tmp_path):
    reg = tmp_path / ".cognirepo" / "watchers"
    return [json.loads(f.read_text()) for f in sorted(reg.glob("*.json"))]


class TestLease:
    def test_exclusive_in_process_and_reports_owner(self, isolated_cognirepo, tmp_path):
        from interface.cli import daemon
        lease = daemon.acquire_watcher_lease(str(tmp_path))
        try:
            with pytest.raises(daemon.WatcherBusy) as exc:
                daemon.acquire_watcher_lease(str(tmp_path))
            assert exc.value.owner == os.getpid()
        finally:
            lease.release()
        daemon.acquire_watcher_lease(str(tmp_path)).release()      # free again after release

    def test_guard_refuses_when_lease_is_held(self, isolated_cognirepo, tmp_path):
        from interface.cli import daemon
        lease = daemon.acquire_watcher_lease(str(tmp_path))
        created = []
        try:
            ran = daemon.run_watcher_with_crash_guard(lambda: created.append(1), lambda o: None,
                                                      str(tmp_path), "s", 0.1)
        finally:
            lease.release()
        assert ran is False and created == []
        assert not list((tmp_path / ".cognirepo" / "watchers").glob("*.json"))   # nothing registered/heartbeat

    def test_standby_wait_can_be_cancelled(self, isolated_cognirepo, tmp_path):
        import threading
        from interface.cli import daemon
        lease = daemon.acquire_watcher_lease(str(tmp_path))
        stop = threading.Event()
        threading.Timer(0.3, stop.set).start()
        try:
            assert daemon.wait_for_watcher_lease(str(tmp_path), poll=0.05, stop=stop) is None
        finally:
            lease.release()


@pytest.mark.timeout(120)
class TestExactlyOneObserver:
    def test_n_processes_started_together_run_exactly_one_observer(self, isolated_cognirepo, tmp_path):
        procs = [_spawn(tmp_path) for _ in range(5)]
        try:
            assert _wait(lambda: len(_marks(tmp_path, "started")) >= 1)
            assert _wait(lambda: len(_marks(tmp_path, "refused")) == 4)
            time.sleep(0.5)
            started = _marks(tmp_path, "started")
            assert len(started) == 1, f"observers started by pids {started}"
            recs = _registry(tmp_path)
            assert [r["pid"] for r in recs] == started                 # only the holder registered
            hb = json.loads((tmp_path / ".cognirepo" / "watchers" / "heartbeat").read_text())
            assert hb["pid"] == started[0]                             # and only it writes the heartbeat
        finally:
            _reap(*procs)

    def test_killing_the_holder_lets_a_standby_session_take_over(self, isolated_cognirepo, tmp_path):
        holder = _spawn(tmp_path)
        assert _wait(lambda: _marks(tmp_path, "started") == [holder.pid])
        standby = [_spawn(tmp_path, standby=True) for _ in range(2)]
        try:
            time.sleep(0.6)
            assert _marks(tmp_path, "started") == [holder.pid]         # standbys did not start observers
            holder.send_signal(signal.SIGKILL)                          # crash: no cleanup runs
            holder.wait(timeout=10)
            assert _wait(lambda: len(_marks(tmp_path, "started")) == 2)
            time.sleep(0.6)
            started = _marks(tmp_path, "started")
            assert len(started) == 2 and holder.pid in started          # exactly one NEW observer
            new = next(p for p in started if p != holder.pid)
            assert new in [s.pid for s in standby]
            assert _wait(lambda: any(r["pid"] == new for r in _registry(tmp_path)))
        finally:
            _reap(holder, *standby)

    def test_clean_exit_releases_the_lease(self, isolated_cognirepo, tmp_path):
        p = _spawn(tmp_path)
        assert _wait(lambda: _marks(tmp_path, "started") == [p.pid])
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=30)
        from interface.cli import daemon
        daemon.acquire_watcher_lease(str(tmp_path)).release()


class TestEmbeddedWatcherIsNotKilledByStop:
    def test_stop_refuses_to_signal_the_host_process(self, isolated_cognirepo, tmp_path):
        from interface.cli import daemon
        p = _spawn(tmp_path, kind="embedded")
        try:
            assert _wait(lambda: any(r.get("kind") == "embedded" for r in _registry(tmp_path)))
            assert daemon.stop_watcher_and_wait(str(p.pid)) == "embedded"
            time.sleep(0.5)
            assert p.poll() is None                                    # the "serve" process is untouched
        finally:
            _reap(p)


_SERVE_LIKE = """
import os, sys, time
sys.path.insert(0, {repo!r})
from interface.cli import daemon
daemon._STANDBY_POLL_SECS = 0.2
from interface.cli.main import _start_watcher_bg
_start_watcher_bg({wp!r})
print("ready", flush=True)
time.sleep(120)
"""


@pytest.mark.timeout(180)
def test_serve_sessions_share_one_watcher_and_one_takes_over(real_watcher_spawn, isolated_cognirepo, tmp_path):
    """What `cognirepo serve` does: every session calls _start_watcher_bg(). Three sessions => ONE
    real watcher (graph/index loaded, registered, 'embedded'); killing it => another takes over."""
    (tmp_path / "a.py").write_text("def f():\n    pass\n")
    env = dict(os.environ, COGNIREPO_DIR=os.path.join(str(tmp_path), ".cognirepo"))
    os.makedirs(os.path.join(str(tmp_path), ".cognirepo", "watchers"), exist_ok=True)
    code = _SERVE_LIKE.format(repo=_REPO, wp=str(tmp_path))
    procs = []
    for _ in range(3):
        p = subprocess.Popen([sys.executable, "-c", code], env=env, cwd=str(tmp_path),  # pylint: disable=consider-using-with
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        assert p.stdout.readline().strip() == "ready"
        procs.append(p)
    try:
        assert _wait(lambda: len(_registry(tmp_path)) == 1, 60)
        time.sleep(1.5)
        recs = _registry(tmp_path)
        assert len(recs) == 1 and recs[0]["kind"] == "embedded"
        holder = recs[0]["pid"]
        assert holder in [p.pid for p in procs]
        os.kill(holder, signal.SIGKILL)
        assert _wait(lambda: any(r["pid"] != holder and r["pid"] in [p.pid for p in procs]
                                 for r in _registry(tmp_path)), 60), "no standby session took over"
    finally:
        _reap(*procs)
