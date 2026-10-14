# SPDX-FileCopyrightText: 2026 Ashlesha T
# SPDX-License-Identifier: MIT
"""`cognirepo ui --autostart` policy (#129): loopback-only command, idempotent, opt-in prompt.

The OS backends themselves are tested in tests/test_always_on_watcher.py (shared with #146)."""
from __future__ import annotations

import argparse
from unittest import mock

import pytest

from interface.ui import autostart as backends
from interface.ui import console_autostart as auto


@pytest.fixture
def fake_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(auto, "_config_path", lambda: str(tmp_path / "ui" / "config.json"))
    be = mock.MagicMock()
    be.installed = False

    def install(name, argv, cwd, description=None):
        be.installed = True
        be.last = (name, argv, cwd)
        return f"/units/{name}"

    def uninstall(name):
        was, be.installed = be.installed, False
        return was

    be.install.side_effect, be.uninstall.side_effect = install, uninstall
    monkeypatch.setattr(backends, "backend", lambda: be)
    return be


class TestCommand:
    def test_argv_is_always_loopback_and_never_unsafe(self):
        argv = auto.build_argv()
        assert argv[argv.index("--host") + 1] == "127.0.0.1"
        assert "--unsafe-bind" not in argv and "--serve" in argv and "--no-open" in argv

    def test_enable_installs_the_fixed_command_and_records_it(self, fake_backend, tmp_path):
        res = auto.enable(str(tmp_path))
        assert res.ok and fake_backend.last[0] == auto.UNIT_NAME
        assert fake_backend.last[1] == auto.build_argv()
        assert auto.load_config()["autostart"] is True

    def test_disable_is_idempotent(self, fake_backend, tmp_path):
        auto.enable(str(tmp_path))
        first, second = auto.disable(), auto.disable()
        assert first.changed and "removed" in first.detail
        assert not second.changed and "not enabled" in second.detail
        assert auto.load_config()["autostart"] is False

    def test_backend_failure_is_reported_not_swallowed(self, monkeypatch, tmp_path):
        be = mock.MagicMock()
        be.install.side_effect = backends.AutostartError("systemctl refused")
        monkeypatch.setattr(backends, "backend", lambda: be)
        monkeypatch.setattr(auto, "_config_path", lambda: str(tmp_path / "c.json"))
        res = auto.enable(str(tmp_path))
        assert not res.ok and "systemctl refused" in res.detail


class TestFirstRunPrompt:
    def test_default_is_no_and_asked_once(self, fake_backend):
        asked = []
        assert auto.maybe_prompt("/r", lambda p: asked.append(p) or "", is_tty=True) is None
        assert asked == [auto.PROMPT] and not fake_backend.install.called
        assert auto.maybe_prompt("/r", lambda p: asked.append(p) or "y", is_tty=True) is None
        assert len(asked) == 1  # never asked twice

    def test_yes_enables(self, fake_backend):
        res = auto.maybe_prompt("/r", lambda p: "y", is_tty=True)
        assert res is not None and res.ok and fake_backend.installed

    def test_non_interactive_never_asks_or_records(self, fake_backend):
        assert auto.maybe_prompt("/r", lambda p: pytest.fail("must not ask"), is_tty=False) is None
        assert "autostart_asked" not in auto.load_config()

    def test_eof_means_no(self, fake_backend):
        def boom(_):
            raise EOFError
        assert auto.maybe_prompt("/r", boom, is_tty=True) is None


class TestCliFlag:
    def test_autostart_on_off_flag(self, fake_backend, capsys):
        from interface.ui import cli
        ns = argparse.Namespace(host="127.0.0.1", port=None, no_open=True, serve=False, stop=False,
                                unsafe_bind=False, allow_origin=None, autostart="on")
        assert cli.run_ui(ns) == 0 and fake_backend.installed
        ns.autostart = "off"
        assert cli.run_ui(ns) == 0 and not fake_backend.installed
        assert cli.run_ui(ns) == 0 and "not enabled" in capsys.readouterr().out
