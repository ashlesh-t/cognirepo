# Copyright (c) 2026 Ashlesh T. — AGPL-3.0 (see LICENSE)
"""Cross-platform process helpers and the watcher's platform branches (#148)."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from unittest import mock

import pytest

from core.config import procutil


class TestPidAlive:
    def test_own_pid_is_alive_and_bogus_ones_are_not(self):
        assert procutil.pid_alive(os.getpid())
        assert not procutil.pid_alive(0) and not procutil.pid_alive(-5)
        assert not procutil.pid_alive("12")  # type: ignore[arg-type]

    @pytest.mark.skipif(procutil.IS_WINDOWS, reason="POSIX child handling")
    def test_exited_child_is_not_alive(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        assert not procutil.pid_alive(proc.pid)

    def test_windows_never_signals_the_pid(self, monkeypatch):
        """os.kill(pid, 0) TERMINATES a process on Windows; the probe must not go near it."""
        monkeypatch.setattr(procutil, "IS_WINDOWS", True)
        monkeypatch.setattr(procutil, "_windows_alive", lambda pid: pid == 42, raising=True)
        with mock.patch("os.kill", side_effect=AssertionError("must not signal")):
            assert procutil.pid_alive(42) is True
            assert procutil.pid_alive(43) is False


class TestStopAndDetach:
    def test_request_stop_sends_sigterm(self):
        with mock.patch("os.kill") as kill:
            procutil.request_stop(7)
        kill.assert_called_once_with(7, signal.SIGTERM)

    def test_force_kill_falls_back_where_sigkill_does_not_exist(self, monkeypatch):
        monkeypatch.delattr(signal, "SIGKILL", raising=False)
        with mock.patch("os.kill") as kill:
            procutil.force_kill(7)
        kill.assert_called_once_with(7, signal.SIGTERM)

    def test_detach_kwargs_per_platform(self, monkeypatch):
        monkeypatch.setattr(procutil, "IS_WINDOWS", False)
        assert procutil.detach_kwargs() == {"start_new_session": True, "close_fds": True}
        monkeypatch.setattr(procutil, "IS_WINDOWS", True)
        kw = procutil.detach_kwargs()
        assert "start_new_session" not in kw          # not accepted on Windows
        assert kw["creationflags"] & 0x00000008       # DETACHED_PROCESS

    def test_spawn_uses_the_platform_detach_kwargs(self, tmp_path, monkeypatch):
        from interface.cli import daemon
        monkeypatch.setattr(procutil, "IS_WINDOWS", True)
        with mock.patch.object(daemon.subprocess, "Popen") as popen:
            daemon.spawn_detached_watcher(str(tmp_path), str(tmp_path / "w.log"))
        kwargs = popen.call_args.kwargs
        assert "creationflags" in kwargs and "start_new_session" not in kwargs


class TestWatchCommandNotGated:
    @pytest.mark.parametrize("plat", ["darwin", "win32"])
    def test_watch_status_runs_on_non_linux(self, plat, tmp_path, monkeypatch, capsys):
        from interface.cli import main as cli
        monkeypatch.setattr(sys, "platform", plat)
        with mock.patch.object(sys, "argv", ["cognirepo", "watch", "--status", "--path", str(tmp_path)]):
            cli.main()                                  # used to sys.exit(2) with "Linux only"
        assert "Daemon" in capsys.readouterr().out
