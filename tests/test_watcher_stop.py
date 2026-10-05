# pylint: disable=missing-docstring, import-outside-toplevel, too-few-public-methods, protected-access
# pylint: disable=redefined-outer-name, unused-argument, duplicate-code
# SPDX-FileCopyrightText: 2026 Ashlesh T
# SPDX-License-Identifier: MIT
#
# This file is part of CogniRepo — https://github.com/ashlesh-t/cognirepo
# Licensed under MIT. See LICENSE file in repository root.

"""
tests/test_watcher_stop.py — COGNIREPO-125 / COGNIREPO-126.

#126: `list --stop` must report success only once the watcher process is really gone (waiting,
then escalating to SIGKILL), clear the registration only after that, and a watcher must not be
able to swallow its own stop request.
#125: the generated systemd unit must start a real foreground mode.
"""
from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"),
                                reason="daemon management is Linux-only")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _spawn(code: str, *, argv0=None, marker: bool = True) -> subprocess.Popen:
    """A child python that prints 'ready' once its signal handlers are installed."""
    cmd = [argv0 or sys.executable, "-S", "-c", code]
    if marker:
        cmd.append("cognirepo-test-watcher")   # makes /proc/<pid>/cmdline look like a cognirepo process
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)  # pylint: disable=consider-using-with
    assert proc.stdout.readline().strip() == "ready"
    return proc


_COOPERATIVE = "import signal, sys, time\n" \
    "signal.signal(signal.SIGTERM, lambda *a: (time.sleep({delay}), sys.exit(0)))\n" \
    "print('ready', flush=True)\ntime.sleep(60)\n"
_STUBBORN = "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n" \
    "print('ready', flush=True)\ntime.sleep(60)\n"


def _register(proc: subprocess.Popen, tmp_path) -> Path:
    from interface.cli import daemon
    daemon.register_watcher(proc.pid, f"watcher-{proc.pid}", str(tmp_path), "log")
    return daemon._pid_file(proc.pid)


def _reap(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=10)


class TestStopWatcherWaitsForExit:
    def test_cooperative_watcher_is_stopped_and_registration_cleared_after_exit(self, isolated_cognirepo, tmp_path):
        from interface.cli import daemon
        proc = _spawn(_COOPERATIVE.format(delay=0.5))
        pid_file = _register(proc, tmp_path)
        try:
            t0 = time.time()
            assert daemon.stop_watcher_and_wait(str(proc.pid), timeout=10) == "stopped"
            assert time.time() - t0 >= 0.4, "returned before the process finished its shutdown"
            assert proc.poll() == 0 and not pid_file.exists()
        finally:
            _reap(proc)

    def test_registration_is_kept_while_the_watcher_is_still_alive(self, isolated_cognirepo, tmp_path):
        """The bug: the PID file was removed immediately, so `--ensure-running` started a 2nd watcher."""
        from interface.cli import daemon
        proc = _spawn(_COOPERATIVE.format(delay=1.5))
        pid_file = _register(proc, tmp_path)
        result: list[str] = []
        stopper = threading.Thread(target=lambda: result.append(daemon.stop_watcher_and_wait(str(proc.pid), timeout=10)))
        try:
            stopper.start()
            time.sleep(0.6)                                   # SIGTERM has been sent, process still flushing
            assert proc.poll() is None, "test setup: process should still be shutting down"
            assert pid_file.exists(), "registration was cleared while the watcher was still running"
            assert daemon.is_watcher_running_for_path(str(tmp_path)) is not None   # ensure-running would NOT start another
            stopper.join(timeout=15)
            assert result == ["stopped"] and not pid_file.exists()
        finally:
            _reap(proc)
            stopper.join(timeout=5)

    def test_a_watcher_that_ignores_sigterm_is_escalated_to_sigkill(self, isolated_cognirepo, tmp_path):
        from interface.cli import daemon
        proc = _spawn(_STUBBORN)
        pid_file = _register(proc, tmp_path)
        try:
            assert daemon.stop_watcher_and_wait(str(proc.pid), timeout=0.6, kill_wait=5) == "killed"
            assert proc.wait(timeout=5) == -signal.SIGKILL
            assert not pid_file.exists()
        finally:
            _reap(proc)

    def test_a_recycled_pid_is_never_sigkilled(self, isolated_cognirepo, tmp_path):
        """If the pid no longer looks like cognirepo we must not SIGKILL it — and we say so."""
        from interface.cli import daemon
        stranger = tmp_path / "plainpython"
        stranger.symlink_to(sys.executable)
        proc = _spawn(_STUBBORN, argv0=str(stranger), marker=False)
        pid_file = _register(proc, tmp_path)
        try:
            assert daemon.stop_watcher_and_wait(str(proc.pid), timeout=0.4, kill_wait=1) == "failed"
            assert proc.poll() is None, "a non-cognirepo process was killed"
            assert pid_file.exists(), "registration must stay when the process is still running"
        finally:
            _reap(proc)

    def test_unknown_watcher_is_not_found(self, isolated_cognirepo):
        from interface.cli import daemon
        assert daemon.stop_watcher_and_wait("424242") == "not_found"
        assert daemon.stop_watcher("424242") is False

    def test_stop_watcher_bool_wrapper(self, isolated_cognirepo, tmp_path):
        from interface.cli import daemon
        proc = _spawn(_COOPERATIVE.format(delay=0.1))
        _register(proc, tmp_path)
        try:
            assert daemon.stop_watcher(str(proc.pid)) is True
        finally:
            _reap(proc)


class TestStopCommandOutput:
    def _run_list_stop(self, monkeypatch, capsys, outcome):
        from interface.cli import daemon
        from interface.cli import main as cli
        monkeypatch.setattr(daemon, "stop_watcher_and_wait", lambda *_a, **_k: outcome)
        monkeypatch.setattr(sys, "argv", ["cognirepo", "list", "-n", "123", "--stop"])
        code = 0
        try:
            cli._main()
        except SystemExit as exc:
            code = exc.code or 0
        out = capsys.readouterr()
        return code, out.out + out.err

    def test_stopped(self, monkeypatch, capsys):
        code, text = self._run_list_stop(monkeypatch, capsys, "stopped")
        assert code == 0 and "stopped" in text and "Sent SIGTERM" not in text

    def test_killed_warns_about_unflushed_edits(self, monkeypatch, capsys):
        code, text = self._run_list_stop(monkeypatch, capsys, "killed")
        assert code == 0 and "SIGKILL" in text and "index-repo --changed-only" in text

    def test_failed_exits_nonzero_and_says_the_registration_was_kept(self, monkeypatch, capsys):
        code, text = self._run_list_stop(monkeypatch, capsys, "failed")
        assert code == 1 and "still running" in text and "registration was left in place" in text

    def test_not_found(self, monkeypatch, capsys):
        code, text = self._run_list_stop(monkeypatch, capsys, "not_found")
        assert code == 1 and "No running watcher found" in text


class TestCrashGuardStop:
    """The watcher process itself: bounded, unswallowable shutdown."""

    @pytest.mark.timeout(30)
    def test_a_swallowed_keyboardinterrupt_still_stops_the_watcher(self, isolated_cognirepo, tmp_path):
        """If something swallows the KeyboardInterrupt the SIGTERM handler raises, the stop flag
        still ends the loop (previously: the watcher kept running until a second SIGTERM)."""
        from interface.cli import daemon
        stopped = []

        class Observer:
            def is_alive(self):
                try:
                    time.sleep(0.05)
                except KeyboardInterrupt:      # swallowed — exactly the failure mode in #126
                    pass
                return True

        threading.Timer(0.4, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
        old = signal.getsignal(signal.SIGTERM)
        try:
            daemon.run_watcher_with_crash_guard(
                create_fn=Observer, stop_fn=lambda o: stopped.append(o),
                watcher_path=str(tmp_path), session_id="t", restart_delay=0.1,
            )
        finally:
            signal.signal(signal.SIGTERM, old)
        assert len(stopped) == 1, "stop_fn (the final flush) must run exactly once"

    @pytest.mark.timeout(30)
    def test_a_stop_during_a_crash_does_not_restart_the_watcher(self, isolated_cognirepo, tmp_path):
        from interface.cli import daemon
        created = []

        def create():
            created.append(1)
            threading.Timer(0.1, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
            time.sleep(0.5)
            raise RuntimeError("crash")

        old = signal.getsignal(signal.SIGTERM)
        try:
            daemon.run_watcher_with_crash_guard(
                create_fn=create, stop_fn=lambda o: None,
                watcher_path=str(tmp_path), session_id="t", restart_delay=0.1,
            )
        finally:
            signal.signal(signal.SIGTERM, old)
        assert len(created) == 1

    def _child(self, tmp_path, body: str) -> subprocess.Popen:
        code = (
            "import os, signal, sys, time\n"
            f"sys.path.insert(0, {_REPO!r})\n"
            "from interface.cli import daemon\n"
            f"WP = {str(tmp_path)!r}\n"
            "daemon.register_watcher(os.getpid(), 'w', WP, 'log')\n"
            + body
        )
        env = dict(os.environ, COGNIREPO_DIR=os.path.join(str(tmp_path), ".cognirepo"))
        os.makedirs(os.path.join(str(tmp_path), ".cognirepo", "watchers"), exist_ok=True)
        proc = subprocess.Popen([sys.executable, "-c", code, "cognirepo-test-watcher"], env=env,  # pylint: disable=consider-using-with
                                cwd=str(tmp_path), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert proc.stdout.readline().strip() == "ready", proc.stderr.read()
        return proc

    @pytest.mark.timeout(60)
    def test_a_hung_final_flush_is_cut_off_by_the_watchdog(self, isolated_cognirepo, tmp_path):
        proc = self._child(tmp_path, (
            "daemon.GRACEFUL_STOP_SECS = 1.0\n"
            "class Obs:\n    def is_alive(self): return True\n"
            "def hang(_o):\n    time.sleep(120)\n"
            "print('ready', flush=True)\n"
            "daemon.run_watcher_with_crash_guard(Obs, hang, WP, 's', 0.1)\n"
        ))
        try:
            time.sleep(1.0)
            t0 = time.time()
            proc.send_signal(signal.SIGTERM)
            assert proc.wait(timeout=15) == 1
            assert time.time() - t0 < 10, "the watchdog should force exit shortly after the grace period"
            registry = tmp_path / ".cognirepo" / "watchers"
            assert not list(registry.glob("*.json")), "registration must be cleaned up even when forced"
        finally:
            _reap(proc)

    @pytest.mark.timeout(60)
    def test_a_second_sigterm_exits_immediately(self, isolated_cognirepo, tmp_path):
        proc = self._child(tmp_path, (
            "class Obs:\n    def is_alive(self): return True\n"
            "def hang(_o):\n    time.sleep(120)\n"
            "print('ready', flush=True)\n"
            "daemon.run_watcher_with_crash_guard(Obs, hang, WP, 's', 0.1)\n"
        ))
        try:
            time.sleep(1.0)
            proc.send_signal(signal.SIGTERM)
            time.sleep(0.5)
            assert proc.poll() is None                       # stuck in its (hung) final flush
            proc.send_signal(signal.SIGTERM)                 # the user insists
            assert proc.wait(timeout=10) == 1
            assert not list((tmp_path / ".cognirepo" / "watchers").glob("*.json"))
        finally:
            _reap(proc)


class TestSystemdUnit:
    def test_unit_uses_a_real_foreground_flag(self, tmp_path):
        from interface.cli.daemon import generate_systemd_unit
        unit = generate_systemd_unit(str(tmp_path))
        line = next(l for l in unit.splitlines() if l.startswith("ExecStart="))
        assert "--foreground" in line and "--daemon-foreground" not in line
        assert "TimeoutStopSec=" in unit and "Restart=on-failure" in unit

    def test_a_repo_path_with_spaces_stays_one_argument(self, tmp_path):
        from interface.cli.daemon import generate_systemd_unit
        repo = tmp_path / "my project"
        repo.mkdir()
        argv = shlex.split(next(l for l in generate_systemd_unit(str(repo)).splitlines()
                                if l.startswith("ExecStart="))[len("ExecStart="):])
        assert argv[argv.index("--path") + 1] == str(repo)

    @pytest.mark.timeout(120)
    @pytest.mark.parametrize("flag", ["--foreground", "--daemon-foreground"])
    def test_the_unit_command_really_starts_and_stops_a_registered_watcher(self, tmp_path, flag):
        """Run the exact argv the unit would use (and the legacy alias older units already have)."""
        proj = tmp_path / "proj"
        (proj / ".cognirepo").mkdir(parents=True)
        (proj / ".cognirepo" / "config.json").write_text(json.dumps({"project_id": "t", "storage": {"encrypt": False}}))
        (proj / "a.py").write_text("def f():\n    return 1\n")
        env = dict(os.environ, PYTHONPATH=_REPO, COGNIREPO_DIR=str(proj / ".cognirepo"))
        base = [sys.executable, "-m", "interface.cli.main"]
        watcher = subprocess.Popen(base + ["watch", "--path", str(proj), flag], cwd=proj, env=env,  # pylint: disable=consider-using-with
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        registry = proj / ".cognirepo" / "watchers"
        try:
            deadline = time.time() + 60
            while time.time() < deadline and not list(registry.glob("*.json")):
                assert watcher.poll() is None, f"watcher exited early: {watcher.stderr.read()[-500:]}"
                time.sleep(0.2)
            records = [json.loads(p.read_text()) for p in registry.glob("*.json")]
            assert records and records[0]["pid"] == watcher.pid, "foreground watcher must register itself"
            status = subprocess.run(base + ["watch", "--path", str(proj), "--status"], cwd=proj, env=env,
                                    capture_output=True, text=True, timeout=60, check=False)
            assert "running" in status.stdout
            second = subprocess.run(base + ["watch", "--path", str(proj), "--foreground"], cwd=proj, env=env,
                                    capture_output=True, text=True, timeout=60, check=False)
            assert "already running" in second.stdout            # singleton: no second watcher
            stop = subprocess.run(base + ["list", "-n", str(watcher.pid), "--stop"], cwd=proj, env=env,
                                  capture_output=True, text=True, timeout=90, check=False)
            assert "stopped" in stop.stdout and stop.returncode == 0, stop.stdout + stop.stderr
            assert watcher.poll() is not None, "list --stop reported success but the watcher is still running"
            assert not list(registry.glob("*.json"))
        finally:
            _reap(watcher)
